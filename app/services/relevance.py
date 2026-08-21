"""Deterministic, intent-aware clinical relevance assessment for B2.2B."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import replace
from datetime import date, datetime

from app.models.article import Article
from app.models.assessment import RankedArticle
from app.models.relevance import AssessedCandidate, ClinicalRelevanceAssessment, ClinicalTarget, ConfirmedDrugClass, RelevanceSignal, SearchQualitySummary
from app.models.retrieval import RetrievalBatch
from app.services.evidence import rank_articles

SOURCE_WEIGHTS = {"title": 30, "mesh_major": 30, "mesh": 20, "author_keyword": 18, "abstract": 10}
_CLASS_ORDER = {"direct": 0, "class_level": 1, "contextual": 2, "irrelevant": 3}
_SECTION_ORDER = {"key_evidence": 0, "important_updates": 1, "exploratory_evidence": 2}
RANKING_POLICY_VERSION = "b4.1.2"
RANKING_SAMPLE_SIZE_CAP = 10_000
RANKING_POLICY = (
    "relevance_class > query_intent_match > evidence_tier > study_design > "
    "limitation_count > bounded_reported_sample_size > b2_relevance_score > "
    "evidence_assessment_section > overall_evidence_score > recency > pmid"
)
RANKING_COMPONENT_DIRECTIONS = {
    "relevance_class_order": "ascending; direct=0, class_level=1, contextual=2, irrelevant=3",
    "query_intent_match_order": "ascending; matching intent=-1 before non-matching=0",
    "evidence_tier_order": "ascending; stronger tiers have lower values",
    "study_design_order": "ascending; stronger designs have lower values",
    "limitation_count": "ascending; fewer limitations first",
    "sample_size_sort_order": "ascending; negative bounded reported sample size ranks larger samples first",
    "b2_relevance_score_order": "ascending; negative B2 score ranks higher scores first",
    "evidence_assessment_section_order": "ascending; key=0, important=1, exploratory=2",
    "overall_evidence_score_order": "ascending; negative score ranks higher scores first",
    "recency_sort_order": "ascending; negative ordinal ranks newer dates first",
    "pmid_tie_break": "ascending lexical PMID tie-break",
}
_TIER_ORDER = {"higher_strength": 0, "moderate_strength": 1, "limited_strength": 2, "signal_only": 3, "preclinical": 4, "not_assessable": 5}
_DESIGN_ORDER = {
    "systematic_review_meta_analysis": 0,
    "randomized_controlled_trial": 1,
    "systematic_review_without_meta_analysis": 2,
    "prospective_cohort": 3,
    "retrospective_cohort": 4,
    "case_control": 5,
    "cross_sectional": 6,
    "case_series": 7,
    "case_report": 8,
    "pharmacovigilance_disproportionality": 9,
    "narrative_review": 10,
}
_INTENT_SUFFIX = re.compile(r"\b(?:efficacy|effectiveness|safety|treatment|therapy|management|outcomes?|evidence)\b.*$", re.I)
_INTENTS = {
    "safety": ("safety", "adverse", "side effect", "tolerability", "pharmacovigilance", "faers", "toxicity", "complication"),
    "efficacy": ("efficacy", "effectiveness", "outcome", "response", "benefit", "superior", "noninferior", "randomized", "treatment", "therapy"),
    "emerging_pharmacotherapy": ("emerging pharmacotherapy", "emerging treatment", "drug development", "new indication"),
    "mechanism_research_trends": ("mechanism", "pathway", "research trend", "translational", "novel target"),
}
_PRECLINICAL = ("animals", "mice", "mouse", "murine", "rat", "rats", "zebrafish", "in vitro", "cell line")
_HUMAN = ("patients", "participants", "human", "clinical trial", "cohort", "randomized")
_PRECLINICAL_QUERY = ("animal", "animals", "mouse", "mice", "murine", "rat", "rats", "preclinical", "in vitro", "cell line", "zebrafish")


def parse_clinical_target(topic: str, intervention: str | None = None, condition: str | None = None) -> tuple[str, str, str, tuple[str, ...]]:
    if intervention and condition:
        return intervention.strip(), condition.strip(), "explicit_cli", ()
    i, c = (intervention or "").strip(), (condition or "").strip()
    method, warnings = "explicit_partial", []
    if not c and (match := re.match(r"^(.+?)\s+(?:for|in)\s+(.+?)\s*$", topic, re.I)):
        left, c = match.groups(); i = i or _INTENT_SUFFIX.sub("", left).strip(" ,-:"); method = "conservative_topic_pattern"
    if not i:
        prefix = re.sub(rf"\s+(?:for|in)\s+{re.escape(c)}\s*$", "", topic, flags=re.I) if c else topic
        i = _INTENT_SUFFIX.sub("", prefix).strip(" ,-:")
    if not i or not c:
        warnings.append("Could not confidently identify both intervention and condition; direct and class-level evidence require both targets")
        method = "ambiguous_topic"
    return i, c, method, tuple(warnings)


def build_clinical_target(topic: str, *, intervention: str | None = None, condition: str | None = None, intervention_rxcuis: tuple[str, ...] = (), intervention_labels: tuple[str, ...] = (), condition_labels: tuple[str, ...] = (), confirmed_classes: tuple[ConfirmedDrugClass, ...] = (), candidate_articles: tuple[Article, ...] = (), warnings: tuple[str, ...] = (), query_intents: tuple[str, ...] = (), human_clinical_query: bool = True, intervention_logic: str = "OR", target_interventions: tuple[str, ...] = ()) -> ClinicalTarget:
    i, c, method, parse_warnings = parse_clinical_target(topic, intervention, condition)
    c_norm = _normalize(c)
    c_uis = {d.ui for a in candidate_articles for d in a.mesh_descriptors if d.ui and _normalize(d.text) == c_norm}
    intervention_terms = _split_intervention_terms(i)
    labels = _unique((*intervention_terms, *intervention_labels))
    inferred_human_query = human_clinical_query and not any(_contains(topic, term) for term in _PRECLINICAL_QUERY)
    return ClinicalTarget(i, c, method, tuple(dict.fromkeys(intervention_rxcuis)), labels, tuple(sorted(c_uis)), _unique((c, *condition_labels)), tuple(confirmed_classes), tuple(dict.fromkeys((*parse_warnings, *warnings))), tuple(dict.fromkeys(query_intents or _infer_intents(topic))), inferred_human_query, intervention_logic.upper() if intervention_logic.upper() in {"OR", "AND"} else "OR", _unique(target_interventions or intervention_terms or labels))


def deduplicate_articles(articles: list[Article]) -> tuple[tuple[Article, ...], tuple[str, ...]]:
    seen, unique, duplicate = set(), [], []
    for article in articles:
        key = article.pmid or f"missing:{len(unique)}"
        if key in seen: duplicate.append(article.pmid)
        else: seen.add(key); unique.append(article)
    return tuple(unique), tuple(dict.fromkeys(duplicate))


def assess_candidate(article: Article, target: ClinicalTarget, assessed_at: datetime) -> ClinicalRelevanceAssessment:
    intervention = _signals(article, "intervention", target.intervention_labels, target.intervention_rxcuis, "rxnorm" if target.intervention_rxcuis else "lexical_target")
    condition = _signals(article, "condition", target.condition_labels, target.condition_mesh_uis, "mesh" if target.condition_mesh_uis else "lexical_target", set(target.condition_mesh_uis))
    classes: list[RelevanceSignal] = []
    for item in target.confirmed_classes:
        classes.extend(_signals(article, "intervention_class", _unique((item.preferred_label, *item.synonyms)), (item.class_id,), item.vocabulary, relationship=f"{item.vocabulary}:{item.relationship}"))
    intents, population = _infer_intents(_text(article)), _population(article)
    focus = _focus(article, intervention, classes, condition)
    coherent_condition = _substantive_condition(condition)
    coherence = "coherent" if condition and focus == "target_intervention_primary" else ("coherent" if coherent_condition and focus == "target_class_primary" else ("background_only" if condition else "not_established"))
    role = _role(article, intervention, focus)
    intervention_role, role_rule, role_span = _requested_intervention_role(article, target.intervention_labels)
    if focus == "target_intervention_primary" and intervention_role in {"incidental_mention", "unresolved"}:
        intervention_role, role_rule, role_span = "primary_intervention", "ROLE_PRIMARY_FOCUS", article.title or None
    intent_match = bool(set(target.query_intents) & set(intents))
    review = []
    if not target.intervention_term or not target.condition_term: review.append("ambiguous_target")
    if intervention and condition and not intent_match and set(target.query_intents) & {"safety", "efficacy"}: review.append("intent_mismatch")
    if intervention and condition and focus == "unknown": review.append("insufficient_focus_signal")
    if target.human_clinical_query and population == "preclinical_only": cls = "irrelevant"
    elif classes and condition and focus == "target_class_primary" and coherence == "coherent" and intent_match: cls = "class_level"
    elif intervention and condition and focus == "target_intervention_primary" and coherence == "coherent" and intent_match and intervention_role in {"primary_intervention", "active_comparator", "combination_component", "prophylaxis_intervention"}: cls = "direct"
    elif condition: cls = "contextual"
    else: cls = "irrelevant"
    active = intervention if cls == "direct" else classes
    score = min(50, sum(x.weight for x in active)) + min(50, sum(x.weight for x in condition))
    return ClinicalRelevanceAssessment(article.pmid, cls, score, tuple((*intervention, *classes)), tuple(condition), "excluded_irrelevant" if cls == "irrelevant" else f"included_{cls}", _reason(cls, target, focus, coherence, role, population, article), assessed_at, target.query_intents, intents, focus, coherence, role, population, bool(review), tuple(review), intervention_role, role_rule, role_span)


def assess_candidates(articles: tuple[Article, ...], target: ClinicalTarget, assessed_at: datetime) -> list[AssessedCandidate]:
    return [AssessedCandidate(a, assess_candidate(a, target, assessed_at)) for a in articles]


def rank_and_select_candidates(candidates: list[AssessedCandidate], fetched_at: datetime, topic: str, report_limit: int) -> tuple[list[RankedArticle], list[AssessedCandidate], list[RankedArticle]]:
    eligible = [c for c in candidates if c.relevance.relevance_class != "irrelevant"]
    by_pmid = {c.article.pmid: c.relevance for c in eligible}
    ranked = [RankedArticle(x.article, x.assessment, by_pmid[x.article.pmid]) for x in rank_articles([c.article for c in eligible], fetched_at, topic)]
    ranked.sort(key=_rank_key); selected = ranked[:report_limit]; selected_pmids = {x.article.pmid for x in selected}; audit = []
    for candidate in candidates:
        relevance = candidate.relevance
        if relevance.relevance_class != "irrelevant" and candidate.article.pmid not in selected_pmids:
            relevance = replace(relevance, decision="excluded_report_limit", reason=f"Excluded from the visible report after ranking because report limit {report_limit} was reached. {relevance.reason}")
        audit.append(AssessedCandidate(candidate.article, relevance))
    return selected, audit, ranked


def build_search_quality_summary(batch: RetrievalBatch, candidates: list[AssessedCandidate], report_limit: int, raw_candidate_count: int | None = None) -> SearchQualitySummary:
    counts = {k: sum(c.relevance.relevance_class == k for c in candidates) for k in _CLASS_ORDER}
    included = sum(c.relevance.decision.startswith("included_") for c in candidates)
    excluded_i = sum(c.relevance.decision == "excluded_irrelevant" for c in candidates); excluded_l = sum(c.relevance.decision == "excluded_report_limit" for c in candidates)
    return SearchQualitySummary(batch.query, batch.total_count, batch.candidate_limit, report_limit, raw_candidate_count if raw_candidate_count is not None else len(batch.articles) + len(batch.duplicate_pmids), len(batch.articles), len(batch.duplicate_pmids), batch.duplicate_pmids, included, excluded_i + excluded_l, counts["direct"], counts["class_level"], counts["contextual"], counts["irrelevant"], excluded_i, excluded_l)


def _signals(article: Article, role: str, labels: tuple[str, ...], ids: tuple[str, ...], vocab: str, mesh_uis: set[str] | None = None, relationship: str = "") -> list[RelevanceSignal]:
    labels = tuple(x for x in labels if _normalize(x)); found, seen = [], set()
    fields = [("title", article.title, "")] + [("mesh_major" if d.major_topic else "mesh", d.text, d.ui) for d in article.mesh_descriptors] + [("author_keyword", x, "") for x in article.keywords]
    fields += [(f"abstract_{_normalize(s.label) or 'unlabelled'}", s.text, "") for s in article.abstract_sections] or [("abstract", article.abstract, "")]
    for source, text, ui in fields:
        label, ui_match = next((x for x in labels if _contains(text, x)), ""), bool(mesh_uis and ui in mesh_uis)
        if source in seen or (not label and not ui_match): continue
        seen.add(source); found.append(RelevanceSignal(role, text if source in {"mesh", "mesh_major", "author_keyword"} else (label or text), label or text, ui if ui_match else (ids[0] if ids else ""), "mesh" if ui_match else vocab, source, SOURCE_WEIGHTS.get(source, 10), relationship))
    return found


def _text(article: Article) -> str: return " ".join((article.title, article.abstract, " ".join(article.keywords), " ".join(x.text for x in article.mesh_descriptors)))
def _infer_intents(text: str) -> tuple[str, ...]: return tuple(k for k, v in _INTENTS.items() if any(_contains(text, x) for x in v)) or ("unknown",)
def _population(article: Article) -> str:
    text = _text(article)
    title = _normalize(article.title)
    primary_abstract = re.split(r"\b(?:in conclusion|conclusion|conclusions)\b", _normalize(article.abstract), maxsplit=1)[0]
    mesh_terms = {_normalize(item.text) for item in article.mesh_descriptors}
    title_pre = any(_contains(title, term) for term in _PRECLINICAL)
    title_human = any(_contains(title, term) for term in _HUMAN)
    mesh_pre = any(term in mesh_terms for term in ("animals", "mice", "mouse", "rats", "rat", "murine", "zebrafish"))
    mesh_human = "humans" in mesh_terms
    pre = any(_contains(text, x) for x in _PRECLINICAL)
    human = any(_contains(text, x) for x in _HUMAN)
    explicit_mixed = bool(re.search(r"\b(?:patients?|participants?|humans?)\b.{0,80}\b(?:mice|mouse|rats?|animals?|in vitro|cell line)\b|\b(?:mice|mouse|rats?|animals?|in vitro|cell line)\b.{0,80}\b(?:patients?|participants?|humans?)\b", primary_abstract))
    if title_pre and not title_human:
        return "preclinical_only"
    if mesh_pre and not mesh_human and not human:
        return "preclinical_only"
    if explicit_mixed:
        return "mixed"
    if title_human or mesh_human:
        return "human"
    if pre and not human:
        return "preclinical_only"
    if pre and human:
        return "mixed"
    if human:
        return "human"
    return "unknown"
def _focus(article: Article, drug: list[RelevanceSignal], classes: list[RelevanceSignal], condition: list[RelevanceSignal]) -> str:
    if not drug and not classes: return "unknown"
    drug_title = any(x.source_field == "title" for x in drug)
    class_title = any(x.source_field == "title" for x in classes)
    structured_substantive = any(x.source_field in {"abstract_results", "abstract_conclusions", "abstract_conclusion", "abstract_methods", "abstract_objectives"} for x in drug)
    review_comparator_only = _is_review_like(article) and _requested_intervention_role(
        article,
        tuple(signal.normalized_label for signal in drug if signal.normalized_label),
    )[0] == "active_comparator"
    text = _normalize(_text(article))
    drug_substantive = any(
        re.search(rf"{re.escape(_normalize(signal.normalized_label))}.{{0,100}}(?:compared|reference|versus|adverse|efficacy|trial)|(?:compared|reference|versus).{{0,100}}{re.escape(_normalize(signal.normalized_label))}", text)
        for signal in drug if _normalize(signal.normalized_label)
    )
    repeated_drug = any(len(re.findall(rf"(?<![a-z0-9]){re.escape(_normalize(signal.normalized_label))}(?![a-z0-9])", text)) >= 2 for signal in drug if _normalize(signal.normalized_label))
    if drug_title:
        return "target_intervention_primary"
    if structured_substantive and repeated_drug and not review_comparator_only:
        return "target_intervention_primary"
    if repeated_drug and drug_substantive and not _is_review_like(article):
        return "target_intervention_primary"
    all_exposed = any(
        re.search(
            rf"\ball\s+(?:patients?|participants?|subjects?|volunteers?)\b.{{0,120}}{re.escape(_normalize(signal.normalized_label))}"
            rf"|\ball\b[^.;]{{0,120}}\b(?:using|receiving|treated\s+with|administered)\b[^.;]{{0,80}}{re.escape(_normalize(signal.normalized_label))}"
            rf"|{re.escape(_normalize(signal.normalized_label))}.{{0,120}}\b(?:administered|given)\s+to\s+all\b",
            text,
        )
        for signal in drug if _normalize(signal.normalized_label)
    )
    if all_exposed: return "target_intervention_primary"
    if class_title or (any(x.source_field == "mesh_major" for x in classes) and any(_contains(text, term) for term in ("adverse", "complication", "risk", "safety"))):
        return "target_class_primary"
    return "background_or_incidental"
def _role(article: Article, drug: list[RelevanceSignal], focus: str) -> str:
    text = f" {_normalize(_text(article))} "
    if focus in {"unknown", "background_or_incidental"} and any(x in text for x in ("artificial intelligence", "digital pathology", "machine learning", " imaging ")): return "research_enabler"
    if focus in {"unknown", "background_or_incidental"} and any(x in text for x in ("mechanism", "pathway", "nitric oxide", "cytochrome")): return "emerging_mechanism"
    return "background_context" if focus in {"unknown", "background_or_incidental"} else "clinical_evidence"


def _requested_intervention_role(article: Article, labels: tuple[str, ...]) -> tuple[str, str, str | None]:
    """Classify the requested drug's grammatical role without topic-specific rules."""
    for label in labels:
        if _contains(article.title, label):
            normalized_title = _normalize(article.title)
            normalized_label = _normalize(label)
            if re.search(rf"\b(?:comparison with|compared with|versus|vs)\b.{{0,80}}{re.escape(normalized_label)}|\b(?:and|or)\s+{re.escape(normalized_label)}\b", normalized_title):
                return "active_comparator", "ROLE_TITLE_ACTIVE_COMPARATOR", article.title
            if re.search(rf"\b(?:combination|combined)\b.{{0,120}}{re.escape(normalized_label)}|{re.escape(normalized_label)}\s*/", normalized_title):
                return "combination_component", "ROLE_TITLE_COMBINATION", article.title
            return "primary_intervention", "ROLE_TITLE_PRIMARY", article.title
    for sentence in re.split(r"(?<=[.!?])\s+", article.abstract or ""):
        normalized = _normalize(sentence)
        label = next((item for item in labels if _contains(normalized, item)), None)
        if not label:
            continue
        if re.search(r"\b(?:prior|previous|historical|already been shown|similar to|plasma levels|pharmacokinetic)\b", sentence, re.I):
            return "pharmacokinetic_reference", "ROLE_BACKGROUND_OR_PK", sentence.strip()
        if re.search(rf"\b(?:combin(?:ing|ed|ation)|group\s+[a-z])\b.{{0,180}}{re.escape(_normalize(label))}", normalized, re.I):
            return "combination_component", "ROLE_COMBINATION_COMPONENT", sentence.strip()
        if re.search(r"\b(?:versus|vs\.?|compared with|compared to)\b.{0,100}" + re.escape(_normalize(label)), normalized, re.I):
            return "active_comparator", "ROLE_ACTIVE_COMPARATOR", sentence.strip()
        if re.search(r"\b(?:randomi[sz]ed|assigned|allocated|received|treated with|administered)\b.{0,100}" + re.escape(_normalize(label)), normalized, re.I):
            return "primary_intervention", "ROLE_EVALUATED_TREATMENT", sentence.strip()
        if re.search(re.escape(_normalize(label)) + r".{0,100}\b(?:versus|vs\.?|compared with|compared to)\b", normalized, re.I):
            return "primary_intervention", "ROLE_EVALUATED_TREATMENT", sentence.strip()
        if re.search(r"\b(?:prophylaxis|prevention)\b", sentence, re.I):
            return "prophylaxis_intervention", "ROLE_PROPHYLAXIS", sentence.strip()
        return "incidental_mention", "ROLE_INCIDENTAL", sentence.strip()
    return "unresolved", "ROLE_UNRESOLVED", None
def _reason(cls: str, target: ClinicalTarget, focus: str, coherence: str, role: str, population: str, article: Article) -> str:
    if population == "preclinical_only" and target.human_clinical_query: return "Excluded as irrelevant: preclinical-only evidence does not satisfy the explicitly human clinical query; it remains retained in the audit JSON."
    if cls == "direct": return "Included as direct evidence: requested intervention has substantive, coherent results and the article intent matches the query."
    if cls == "class_level": return "Included as class-level evidence: an authoritative confirmed class has substantive, coherent results and the article intent matches the query."
    if cls == "contextual": return f"Included as contextual evidence in {'Emerging mechanisms and research trends' if role in {'emerging_mechanism', 'research_enabler'} else 'Background/contextual evidence'}: focus={focus}; requested intervention is not substantively evaluated."
    other_major = next((d.text for d in article.mesh_descriptors if d.major_topic and _normalize(d.text) not in {_normalize(x) for x in (*target.intervention_labels, *target.condition_labels)}), "")
    return "Excluded as irrelevant: requested intervention-condition-intent criteria were not jointly satisfied." + (f" Major MeSH identifies {other_major}." if other_major else "")
def ranking_components(item: RankedArticle) -> dict[str, object]:
    """Return the named, normalized values used by the final ranking tuple."""
    r = item.clinical_relevance
    study = item.assessment.study_assessment
    intent_match = bool(r and set(r.query_intents) & set(r.article_intents))
    raw_sample_size = study.sample_size if study and study.sample_size_status == "reported" and study.sample_size is not None and study.sample_size > 0 else None
    sample_size_ranking_value = min(raw_sample_size, RANKING_SAMPLE_SIZE_CAP) if raw_sample_size is not None else 0
    publication_date = item.article.publication_date
    return {
        "relevance_class": r.relevance_class if r else "irrelevant",
        "relevance_class_order": _CLASS_ORDER.get(r.relevance_class if r else "irrelevant", 3),
        "query_intent_match": intent_match,
        "query_intent_match_order": -int(intent_match),
        "evidence_tier": study.evidence_tier if study else "not_assessable",
        "evidence_tier_order": _TIER_ORDER.get(study.evidence_tier if study else "not_assessable", 6),
        "study_design": study.design_family if study else "unknown",
        "study_design_order": _DESIGN_ORDER.get(study.design_family if study else "unknown", 99),
        "limitation_count": len(study.limitation_codes) if study else 99,
        "reported_sample_size_raw": raw_sample_size,
        "sample_size_ranking_cap": RANKING_SAMPLE_SIZE_CAP,
        "sample_size_ranking_value": sample_size_ranking_value,
        "sample_size_sort_order": -sample_size_ranking_value,
        "b2_relevance_score": r.relevance_score if r else 0,
        "b2_relevance_score_order": -(r.relevance_score if r else 0),
        "evidence_assessment_section": item.assessment.section,
        "evidence_assessment_section_order": _SECTION_ORDER.get(item.assessment.section, 3),
        "overall_evidence_score": item.assessment.overall_score,
        "overall_evidence_score_order": -item.assessment.overall_score,
        "publication_date": publication_date.isoformat() if publication_date else None,
        "publication_date_ordinal": (publication_date or date.min).toordinal(),
        "recency_sort_order": -(publication_date or date.min).toordinal(),
        "pmid_tie_break": item.article.pmid,
    }


def ranking_sort_key_from_components(components: dict[str, object]) -> tuple:
    """Build the production lexicographic key from named canonical components."""
    return (
        components["relevance_class_order"],
        components["query_intent_match_order"],
        components["evidence_tier_order"],
        components["study_design_order"],
        components["limitation_count"],
        components["sample_size_sort_order"],
        components["b2_relevance_score_order"],
        components["evidence_assessment_section_order"],
        components["overall_evidence_score_order"],
        components["recency_sort_order"],
        components["pmid_tie_break"],
    )


def _rank_key(item: RankedArticle) -> tuple:
    return ranking_sort_key_from_components(ranking_components(item))
def _contains(text: str, label: str) -> bool:
    needle = _normalize(label); return bool(needle and re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", f" {_normalize(text)} "))
def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]+", " ", re.sub(r"[-_/]+", " ", unicodedata.normalize("NFKC", value).casefold()))).strip()
def _unique(values: tuple[str, ...]) -> tuple[str, ...]:
    out: dict[str, str] = {}
    for value in values:
        if (key := _normalize(value)): out.setdefault(key, value.strip())
    return tuple(out.values())


def _substantive_condition(signals: list[RelevanceSignal]) -> bool:
    strong_sources = {"title", "mesh_major", "abstract_objectives", "abstract_methods", "abstract_results", "abstract_conclusions", "abstract_conclusion"}
    return any(signal.source_field in strong_sources for signal in signals)


def _is_review_like(article: Article) -> bool:
    return any("review" in value.casefold() or "meta-analysis" in value.casefold() for value in article.publication_types)


def _split_intervention_terms(value: str) -> tuple[str, ...]:
    terms = tuple(part.strip(" ,-:") for part in re.split(r"\s+OR\s+", value, flags=re.I))
    return tuple(term for term in terms if term)
