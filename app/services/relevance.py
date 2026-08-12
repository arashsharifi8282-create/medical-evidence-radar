"""Deterministic clinical relevance assessment and pre-evidence filtering.

Phase B2 deliberately separates clinical relevance from Phase-A study-design
ranking.  Every candidate is assessed first; only non-irrelevant candidates are
then passed to the existing evidence ranker.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import replace
from datetime import date, datetime

from app.models.article import Article
from app.models.assessment import RankedArticle
from app.models.relevance import (
    AssessedCandidate,
    ClinicalRelevanceAssessment,
    ClinicalTarget,
    ConfirmedDrugClass,
    RelevanceSignal,
    SearchQualitySummary,
)
from app.models.retrieval import RetrievalBatch
from app.services.evidence import rank_articles

SOURCE_WEIGHTS = {
    "title": 30,
    "mesh_major": 30,
    "mesh": 20,
    "author_keyword": 18,
    "abstract": 10,
}
_CLASS_ORDER = {"direct": 0, "class_level": 1, "contextual": 2, "irrelevant": 3}
_SECTION_ORDER = {"key_evidence": 0, "important_updates": 1, "exploratory_evidence": 2}
_INTENT_SUFFIX = re.compile(
    r"\b(?:efficacy|effectiveness|safety|treatment|therapy|management|outcomes?|evidence)\b.*$",
    re.IGNORECASE,
)


def parse_clinical_target(
    topic: str,
    intervention: str | None = None,
    condition: str | None = None,
) -> tuple[str, str, str, tuple[str, ...]]:
    """Conservatively split common intervention/condition topic forms.

    Explicit values always win. Ambiguous input is preserved with a warning;
    the caller can still produce contextual audit output without guessing.
    """
    if intervention and condition:
        return intervention.strip(), condition.strip(), "explicit_cli", ()

    warnings: list[str] = []
    inferred_intervention = intervention.strip() if intervention else ""
    inferred_condition = condition.strip() if condition else ""
    method = "explicit_partial"

    if not inferred_condition:
        match = re.match(r"^(.+?)\s+(?:for|in)\s+(.+?)\s*$", topic, re.IGNORECASE)
        if match:
            left, inferred_condition = match.groups()
            if not inferred_intervention:
                inferred_intervention = _INTENT_SUFFIX.sub("", left).strip(" ,-:")
            method = "conservative_topic_pattern"

    if not inferred_intervention:
        # Handles "losartan efficacy and safety in hypertension", where the
        # condition split succeeded and intent words follow the intervention.
        prefix = topic
        if inferred_condition:
            prefix = re.sub(
                rf"\s+(?:for|in)\s+{re.escape(inferred_condition)}\s*$", "", topic, flags=re.IGNORECASE
            )
        inferred_intervention = _INTENT_SUFFIX.sub("", prefix).strip(" ,-:")

    if not inferred_intervention or not inferred_condition:
        warnings.append(
            "Could not confidently identify both intervention and condition; "
            "direct and class-level evidence require both targets"
        )
        method = "ambiguous_topic"

    return inferred_intervention, inferred_condition, method, tuple(warnings)


def build_clinical_target(
    topic: str,
    *,
    intervention: str | None = None,
    condition: str | None = None,
    intervention_rxcuis: tuple[str, ...] = (),
    intervention_labels: tuple[str, ...] = (),
    confirmed_classes: tuple[ConfirmedDrugClass, ...] = (),
    candidate_articles: tuple[Article, ...] = (),
    warnings: tuple[str, ...] = (),
) -> ClinicalTarget:
    """Build a source-backed target and anchor exact condition MeSH UIs."""
    intervention_term, condition_term, method, parse_warnings = parse_clinical_target(
        topic, intervention, condition
    )
    condition_norm = _normalize(condition_term)
    condition_uis = {
        descriptor.ui
        for article in candidate_articles
        for descriptor in article.mesh_descriptors
        if descriptor.ui and _normalize(descriptor.text) == condition_norm
    }
    return ClinicalTarget(
        intervention_term=intervention_term,
        condition_term=condition_term,
        extraction_method=method,
        intervention_rxcuis=tuple(dict.fromkeys(intervention_rxcuis)),
        intervention_labels=_unique_labels((intervention_term, *intervention_labels)),
        condition_mesh_uis=tuple(sorted(condition_uis)),
        condition_labels=_unique_labels((condition_term,)),
        confirmed_classes=tuple(confirmed_classes),
        warnings=tuple(dict.fromkeys((*parse_warnings, *warnings))),
    )


def deduplicate_articles(articles: list[Article]) -> tuple[tuple[Article, ...], tuple[str, ...]]:
    """Keep the first PubMed-ordered record for each PMID and audit duplicates."""
    seen: set[str] = set()
    unique: list[Article] = []
    duplicates: list[str] = []
    for article in articles:
        key = article.pmid or f"missing:{len(unique)}"
        if key in seen:
            duplicates.append(article.pmid)
            continue
        seen.add(key)
        unique.append(article)
    return tuple(unique), tuple(dict.fromkeys(duplicates))


def assess_candidate(
    article: Article,
    target: ClinicalTarget,
    assessed_at: datetime,
) -> ClinicalRelevanceAssessment:
    """Assess one candidate using field-aware intervention and condition signals."""
    intervention = _collect_signals(
        article,
        role="intervention",
        labels=target.intervention_labels,
        concept_ids=target.intervention_rxcuis,
        vocabulary="rxnorm" if target.intervention_rxcuis else "lexical_target",
    )
    condition = _collect_signals(
        article,
        role="condition",
        labels=target.condition_labels,
        concept_ids=target.condition_mesh_uis,
        vocabulary="mesh" if target.condition_mesh_uis else "lexical_target",
        mesh_uis=set(target.condition_mesh_uis),
    )

    class_signals: list[RelevanceSignal] = []
    if not intervention:
        for confirmed in target.confirmed_classes:
            class_signals.extend(
                _collect_signals(
                    article,
                    role="intervention_class",
                    labels=_unique_labels((confirmed.preferred_label, *confirmed.synonyms)),
                    concept_ids=(confirmed.class_id,),
                    vocabulary=confirmed.vocabulary,
                    relationship_source=f"{confirmed.vocabulary}:{confirmed.relationship}",
                )
            )

    if intervention and condition:
        relevance_class = "direct"
        active_intervention = intervention
    elif class_signals and condition:
        relevance_class = "class_level"
        active_intervention = class_signals
    elif condition:
        relevance_class = "contextual"
        active_intervention = class_signals
    else:
        relevance_class = "irrelevant"
        active_intervention = intervention or class_signals

    score = min(50, sum(signal.weight for signal in active_intervention)) + min(
        50, sum(signal.weight for signal in condition)
    )
    decision = "excluded_irrelevant" if relevance_class == "irrelevant" else f"included_{relevance_class}"
    reason = _reason(relevance_class, intervention, class_signals, condition, target, article)
    return ClinicalRelevanceAssessment(
        pmid=article.pmid,
        relevance_class=relevance_class,
        relevance_score=score,
        intervention_signals=tuple((*intervention, *class_signals)),
        condition_signals=tuple(condition),
        decision=decision,
        reason=reason,
        assessed_at=assessed_at,
    )


def assess_candidates(
    articles: tuple[Article, ...], target: ClinicalTarget, assessed_at: datetime
) -> list[AssessedCandidate]:
    return [AssessedCandidate(article, assess_candidate(article, target, assessed_at)) for article in articles]


def rank_and_select_candidates(
    candidates: list[AssessedCandidate],
    fetched_at: datetime,
    topic: str,
    report_limit: int,
) -> tuple[list[RankedArticle], list[AssessedCandidate], list[RankedArticle]]:
    """Run Phase A after relevance filtering, then apply the visible limit."""
    eligible = [candidate for candidate in candidates if candidate.relevance.relevance_class != "irrelevant"]
    relevance_by_pmid = {candidate.article.pmid: candidate.relevance for candidate in eligible}
    ranked = rank_articles([candidate.article for candidate in eligible], fetched_at, topic)
    ranked = [
        RankedArticle(item.article, item.assessment, relevance_by_pmid[item.article.pmid]) for item in ranked
    ]
    ranked.sort(key=_final_rank_key)

    included_pmids = {item.article.pmid for item in ranked[:report_limit]}
    selected = ranked[:report_limit]
    audited: list[AssessedCandidate] = []
    for candidate in candidates:
        relevance = candidate.relevance
        if relevance.relevance_class != "irrelevant" and candidate.article.pmid not in included_pmids:
            relevance = replace(
                relevance,
                decision="excluded_report_limit",
                reason=f"Excluded from the visible report after ranking because report limit {report_limit} was reached. "
                + relevance.reason,
            )
        audited.append(AssessedCandidate(candidate.article, relevance))
    return selected, audited, ranked


def build_search_quality_summary(
    batch: RetrievalBatch,
    candidates: list[AssessedCandidate],
    report_limit: int,
    raw_candidate_count: int | None = None,
) -> SearchQualitySummary:
    counts = {
        key: sum(item.relevance.relevance_class == key for item in candidates)
        for key in ("direct", "class_level", "contextual", "irrelevant")
    }
    included = sum(item.relevance.decision.startswith("included_") for item in candidates)
    excluded_irrelevant = sum(item.relevance.decision == "excluded_irrelevant" for item in candidates)
    excluded_limit = sum(item.relevance.decision == "excluded_report_limit" for item in candidates)
    return SearchQualitySummary(
        query=batch.query,
        total_result_count=batch.total_count,
        candidate_limit=batch.candidate_limit,
        report_limit=report_limit,
        raw_candidate_count=raw_candidate_count if raw_candidate_count is not None else len(batch.articles) + len(batch.duplicate_pmids),
        fetched_candidate_count=len(batch.articles),
        duplicate_count=len(batch.duplicate_pmids),
        duplicate_pmids=batch.duplicate_pmids,
        included_count=included,
        excluded_count=excluded_irrelevant + excluded_limit,
        direct_count=counts["direct"],
        class_level_count=counts["class_level"],
        contextual_count=counts["contextual"],
        irrelevant_count=counts["irrelevant"],
        excluded_irrelevant_count=excluded_irrelevant,
        excluded_report_limit_count=excluded_limit,
    )


def _collect_signals(
    article: Article,
    *,
    role: str,
    labels: tuple[str, ...],
    concept_ids: tuple[str, ...],
    vocabulary: str,
    mesh_uis: set[str] | None = None,
    relationship_source: str = "",
) -> list[RelevanceSignal]:
    valid_labels = tuple(label for label in labels if _normalize(label))
    if not valid_labels and not mesh_uis:
        return []
    signals: list[RelevanceSignal] = []
    fields: list[tuple[str, str, str]] = [("title", article.title, "")]
    fields.extend(
        ("mesh_major" if descriptor.major_topic else "mesh", descriptor.text, descriptor.ui)
        for descriptor in article.mesh_descriptors
    )
    fields.extend(("author_keyword", keyword, "") for keyword in article.keywords)
    fields.append(("abstract", article.abstract, ""))

    seen_fields: set[str] = set()
    for source_field, text, mesh_ui in fields:
        if source_field in seen_fields or not text:
            continue
        label = next((item for item in valid_labels if _contains_phrase(text, item)), "")
        ui_match = bool(mesh_uis and mesh_ui in mesh_uis)
        if not label and not ui_match:
            continue
        seen_fields.add(source_field)
        normalized_label = label or text
        signals.append(
            RelevanceSignal(
                role=role,
                matched_text=text if source_field in ("mesh", "mesh_major", "author_keyword") else normalized_label,
                normalized_label=normalized_label,
                concept_id=(mesh_ui if ui_match else (concept_ids[0] if concept_ids else "")),
                vocabulary="mesh" if ui_match else vocabulary,
                source_field=source_field,
                weight=SOURCE_WEIGHTS[source_field],
                relationship_source=relationship_source,
            )
        )
    return signals


def _final_rank_key(item: RankedArticle) -> tuple:
    relevance = item.clinical_relevance
    return (
        _CLASS_ORDER.get(relevance.relevance_class if relevance else "irrelevant", 3),
        -(relevance.relevance_score if relevance else 0),
        _SECTION_ORDER.get(item.assessment.section, 3),
        -item.assessment.overall_score,
        -(item.article.publication_date or date.min).toordinal(),
        item.article.pmid,
    )


def _reason(
    relevance_class: str,
    intervention: list[RelevanceSignal],
    class_signals: list[RelevanceSignal],
    condition: list[RelevanceSignal],
    target: ClinicalTarget,
    article: Article,
) -> str:
    intervention_fields = _field_summary(intervention)
    class_fields = _field_summary(class_signals)
    condition_fields = _field_summary(condition)
    if relevance_class == "direct":
        return (
            f"Included as direct evidence: {target.intervention_term} matched in {intervention_fields}; "
            f"{target.condition_term} matched in {condition_fields}."
        )
    if relevance_class == "class_level":
        confirmed = target.confirmed_classes[0]
        return (
            f"Included as class-level evidence: {confirmed.preferred_label} is a confirmed "
            f"{confirmed.vocabulary} parent of RXCUI {confirmed.source_rxcui} and matched in {class_fields}; "
            f"{target.condition_term} matched in {condition_fields}."
        )
    if relevance_class == "contextual":
        return (
            f"Background only: {target.condition_term} matched in {condition_fields}, but "
            f"{target.intervention_term or 'the requested intervention'} and no confirmed parent class were found."
        )
    if intervention or class_signals:
        conflict = _major_mesh_conflict(article, target)
        suffix = f" Major MeSH instead identifies {conflict}." if conflict else ""
        return (
            f"Excluded as irrelevant: {target.intervention_term or 'the requested intervention'} matched, "
            f"but the requested condition {target.condition_term or '(unspecified)'} was not supported.{suffix}"
        )
    return "Excluded as irrelevant: neither the requested intervention nor condition was supported."


def _major_mesh_conflict(article: Article, target: ClinicalTarget) -> str:
    ignored = {_normalize(label) for label in (*target.intervention_labels, *target.condition_labels)}
    labels = [
        descriptor.text
        for descriptor in article.mesh_descriptors
        if descriptor.major_topic and _normalize(descriptor.text) not in ignored
    ]
    return ", ".join(labels[:3])


def _field_summary(signals: list[RelevanceSignal]) -> str:
    labels = {"mesh_major": "major MeSH", "mesh": "MeSH", "author_keyword": "author keywords"}
    return ", ".join(labels.get(signal.source_field, signal.source_field) for signal in signals) or "no fields"


def _contains_phrase(text: str, label: str) -> bool:
    haystack = f" {_normalize(text)} "
    needle = _normalize(label)
    if not needle:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", haystack) is not None


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    value = re.sub(r"[-_/]+", " ", value)
    value = re.sub(r"[^a-z0-9\s]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _unique_labels(values: tuple[str, ...]) -> tuple[str, ...]:
    unique: dict[str, str] = {}
    for value in values:
        normalized = _normalize(value)
        if normalized:
            unique.setdefault(normalized, value.strip())
    return tuple(unique.values())
