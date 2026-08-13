"""Local file persistence for fetched PubMed results.

This module is pure: it takes ranked :class:`RankedArticle` records plus metadata
and writes machine-readable JSON snapshots, human-readable Markdown reports,
and standalone HTML reports to timestamped files. No network calls are made here.
"""

from __future__ import annotations

import html
import hashlib
import json
import re
import unicodedata
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from app.models.article import Article
from app.models.assessment import RankedArticle
from app.models.concept import ArticleConceptLink, ConceptNormalizationResult, NormalizedConcept
from app.models.relevance import (
    AssessedCandidate,
    ClinicalRelevanceAssessment,
    ClinicalTarget,
    ConfirmedDrugClass,
    RelevanceSignal,
    SearchQualitySummary,
)
from app.models.study import StudyAssessment
from app.services.evidence import assess_article
from app.services.clinical_extraction import extract_clinical
from app.services.report_policy import load_policy, route_report_section
from app.models.topic_profile import CandidateTerm, TopicProfile

DEFAULT_JSON_DIR = Path("data/raw/pubmed")
DEFAULT_MD_DIR = Path("reports/pubmed")
DEFAULT_HTML_DIR = Path("reports/pubmed")
DEFAULT_CONCEPT_DIR = Path("data/concepts")
MAX_QUERY_SLUG_LENGTH = 120


def _report_ranked(ranked: list[RankedArticle]) -> list[RankedArticle]:
    """Apply the active placement policy once for every renderer."""
    policy = load_policy()
    principal_limit = int(policy["defaults"]["principal_article_limit"])
    if not any(item.clinical_relevance for item in ranked):
        return list(ranked)
    placed = [(item, route_report_section(item)) for item in ranked]
    key = [item for item, placement in placed if placement[0] == "key_evidence" and placement[1]]
    selected_key = {item.article.pmid for item in key[:principal_limit]}
    return [item for item, placement in placed if placement[1] and (placement[0] != "key_evidence" or item.article.pmid in selected_key)]


def _display_value(value, default: str = "Not reported") -> str:
    if value is None or value == "" or value in {"unknown", "unclear", "not_reported", "not_extractable", "not_applicable"}:
        return default
    return str(value).replace("_", " ").capitalize()


def _clinical_card_data(item: RankedArticle) -> dict:
    extraction = extract_clinical(item.article)
    return {
        "population": extraction.population.description or _display_value(extraction.population.scope),
        "intervention": "; ".join(i.source_text for i in extraction.interventions if i.source_text) or "Not reported",
        "comparator": extraction.comparator.source_text or "Not reported",
        "outcomes": tuple(o.name for o in extraction.outcomes) or ("Not extractable from abstract",),
        "effects": tuple(o.effect_value for o in extraction.outcomes if o.effect_value) or ("Not reported",),
        "safety": tuple(s.event_name for s in extraction.safety_findings) or ("No safety finding extractable from abstract",),
        "limitations": tuple(item.assessment.study_assessment.limitation_codes if item.assessment.study_assessment else ()) or ("Not reported",),
        "spans": tuple(p.supporting_span for p in extraction.population.provenance),
        "abstract": item.article.abstract or "Abstract not available in PubMed.",
    }


def _article_to_dict(article: Article) -> dict:
    """Convert an :class:`Article` into a JSON-serializable dict."""
    return {
        "pmid": article.pmid,
        "title": article.title,
        "abstract": article.abstract,
        "authors": list(article.authors),
        "journal": article.journal,
        "publication_date": (
            article.publication_date.isoformat() if article.publication_date else None
        ),
        "publication_date_raw": article.publication_date_raw,
        "electronic_publication_date": (
            article.electronic_publication_date.isoformat()
            if article.electronic_publication_date
            else None
        ),
        "is_epub_ahead_of_print": article.is_epub_ahead_of_print,
        "publication_types": list(article.publication_types),
        "doi": article.doi,
        "pubmed_url": article.pubmed_url,
        "source": article.source,
        "mesh_headings": list(article.mesh_headings),
        "mesh_descriptors": [
            {
                "text": descriptor.text,
                "ui": descriptor.ui,
                "major_topic": descriptor.major_topic,
                "supporting_pmid": descriptor.supporting_pmid,
            }
            for descriptor in article.mesh_descriptors
        ],
        "keywords": list(article.keywords),
        "abstract_sections": [
            {"label": section.label, "text": section.text}
            for section in article.abstract_sections
        ],
    }


def _assessment_to_dict(assessment) -> dict:
    """Convert an :class:`EvidenceAssessment` into a JSON-serializable dict."""
    payload = {
        "evidence_level": assessment.evidence_level,
        "evidence_level_label": assessment.evidence_level_label,
        "relevance_score": assessment.relevance_score,
        "evidence_score": assessment.evidence_score,
        "overall_score": assessment.overall_score,
        "is_future_issue_dated": assessment.is_future_issue_dated,
        "is_electronic_only": assessment.is_electronic_only,
        "has_abstract": assessment.has_abstract,
        "abstract_status": assessment.abstract_status,
        "reasons": list(assessment.reasons),
        "limitations": list(assessment.limitations),
        "section": assessment.section,
    }
    study = assessment.study_assessment
    if study is not None:
        payload["study_assessment"] = _study_assessment_to_dict(study)
    return payload


def _study_assessment_to_dict(study: StudyAssessment) -> dict:
    return {
        "design_family": study.design_family,
        "design_subtype": study.design_subtype,
        "population_scope": study.population_scope,
        "result_status": study.result_status,
        "evidence_tier": study.evidence_tier,
        "confidence": study.confidence,
        "needs_review": study.needs_review,
        "sample_size": study.sample_size,
        "sample_size_status": study.sample_size_status,
        "comparator_status": study.comparator_status,
        "comparator_text": study.comparator_text,
        "randomized": study.randomized,
        "blinded": study.blinded,
        "prospective": study.prospective,
        "retrospective": study.retrospective,
        "multicenter": study.multicenter,
        "treatment_duration_text": study.treatment_duration_text,
        "follow_up_text": study.follow_up_text,
        "data_source_type": study.data_source_type,
        "limitation_codes": list(study.limitation_codes),
        "matched_signals": list(study.matched_signals),
        "supporting_spans": [
            {"field": span.field, "source_type": span.source_type, "text": span.text, "rule_id": span.rule_id}
            for span in study.supporting_spans
        ],
        "assessment_reasons": list(study.assessment_reasons),
        "rule_version": study.rule_version,
    }


def _candidate_to_dict(c: CandidateTerm) -> dict:
    return {
        "term": c.term,
        "source": c.source,
        "document_frequency": c.document_frequency,
        "evidence_max": c.evidence_max,
        "recency_days": c.recency_days,
        "direct_topic_overlap": c.direct_topic_overlap,
        "supporting_articles": list(c.supporting_articles),
        "score": c.score,
        "reasons": list(c.reasons),
        "accepted": c.accepted,
    }


def _ranked_to_dict(r: RankedArticle) -> dict:
    """Convert a :class:`RankedArticle` into a JSON-serializable dict."""
    d = _article_to_dict(r.article)
    d["assessment"] = _assessment_to_dict(r.assessment)
    d["ranking_audit"] = _ranking_audit(r)
    if r.clinical_relevance:
        d["clinical_relevance"] = _clinical_relevance_to_dict(r.clinical_relevance)
    section, visible, reason = route_report_section(r)
    d["structured_clinical_extraction"] = asdict(extract_clinical(r.article))
    d["report_placement"] = {"section": section, "visible": visible, "reason": reason}
    return d


def _ranking_audit(ranked: RankedArticle) -> dict:
    """Serialize the named lexicographic ranking components for replay."""
    relevance = ranked.clinical_relevance
    study = ranked.assessment.study_assessment
    return {
        "policy": "relevance_class > query_intent_match > report_section > evidence_tier > study_design > comparator_suitability > extraction_completeness > bounded_sample_size > recency > pmid",
        "relevance_class": relevance.relevance_class if relevance else None,
        "query_intent_match": bool(relevance and set(relevance.query_intents) & set(relevance.article_intents)),
        "evidence_tier": study.evidence_tier if study else None,
        "study_design": study.design_family if study else None,
        "limitation_count": len(study.limitation_codes) if study else None,
        "bounded_sample_size": min(study.sample_size, 10000) if study and study.sample_size is not None else None,
        "relevance_score": relevance.relevance_score if relevance else None,
        "section": ranked.assessment.section,
        "overall_score": ranked.assessment.overall_score,
        "publication_date": ranked.article.publication_date.isoformat() if ranked.article.publication_date else None,
        "pmid": ranked.article.pmid,
    }


def _signal_to_dict(signal: RelevanceSignal) -> dict:
    return {
        "role": signal.role,
        "matched_text": signal.matched_text,
        "normalized_label": signal.normalized_label,
        "concept_id": signal.concept_id,
        "vocabulary": signal.vocabulary,
        "source_field": signal.source_field,
        "weight": signal.weight,
        "relationship_source": signal.relationship_source,
    }


def _clinical_relevance_to_dict(assessment: ClinicalRelevanceAssessment) -> dict:
    return {
        "pmid": assessment.pmid,
        "relevance_class": assessment.relevance_class,
        "relevance_score": assessment.relevance_score,
        "matched_intervention_signals": [
            _signal_to_dict(item) for item in assessment.intervention_signals
        ],
        "matched_condition_signals": [
            _signal_to_dict(item) for item in assessment.condition_signals
        ],
        "decision": assessment.decision,
        "reason": assessment.reason,
        "query_intents": list(assessment.query_intents),
        "article_intents": list(assessment.article_intents),
        "article_focus": assessment.article_focus,
        "coherence_status": assessment.coherence_status,
        "content_role": assessment.content_role,
        "population_scope": assessment.population_scope,
        "needs_review": assessment.needs_review,
        "review_reasons": list(assessment.review_reasons),
        "assessed_at": assessment.assessed_at.isoformat(),
    }


def _class_to_dict(item: ConfirmedDrugClass) -> dict:
    return {
        "class_id": item.class_id,
        "preferred_label": item.preferred_label,
        "vocabulary": item.vocabulary,
        "relationship": item.relationship,
        "source_rxcui": item.source_rxcui,
        "synonyms": list(item.synonyms),
    }


def _target_to_dict(target: ClinicalTarget) -> dict:
    return {
        "intervention_term": target.intervention_term,
        "condition_term": target.condition_term,
        "extraction_method": target.extraction_method,
        "intervention_rxcuis": list(target.intervention_rxcuis),
        "intervention_labels": list(target.intervention_labels),
        "condition_mesh_uis": list(target.condition_mesh_uis),
        "condition_labels": list(target.condition_labels),
        "confirmed_classes": [_class_to_dict(item) for item in target.confirmed_classes],
        "warnings": list(target.warnings),
        "query_intents": list(target.query_intents),
        "human_clinical_query": target.human_clinical_query,
        "intervention_logic": target.intervention_logic,
        "target_interventions": list(target.target_interventions),
    }


def _quality_to_dict(summary: SearchQualitySummary) -> dict:
    return {
        "total_pubmed_result_count": summary.total_result_count,
        "fetched_candidate_count": summary.fetched_candidate_count,
        "raw_candidate_count": summary.raw_candidate_count,
        "included_count": summary.included_count,
        "excluded_count": summary.excluded_count,
        "direct_count": summary.direct_count,
        "class_level_count": summary.class_level_count,
        "contextual_count": summary.contextual_count,
        "irrelevant_count": summary.irrelevant_count,
        "excluded_irrelevant_count": summary.excluded_irrelevant_count,
        "excluded_report_limit_count": summary.excluded_report_limit_count,
        "duplicate_count": summary.duplicate_count,
        "duplicate_pmids": list(summary.duplicate_pmids),
        "original_query": summary.query,
        "candidate_limit": summary.candidate_limit,
        "report_limit": summary.report_limit,
    }


def _concept_to_dict(concept: NormalizedConcept) -> dict:
    return {
        "concept_id": concept.concept_id,
        "vocabulary": concept.vocabulary,
        "preferred_label": concept.preferred_label,
        "original_term": concept.original_term,
        "concept_type": concept.concept_type,
        "match_method": concept.match_method,
        "confidence": concept.confidence,
        "supporting_pmids": list(concept.supporting_pmids),
        "source_fields": list(concept.source_fields),
    }


def _concept_link_to_dict(link: ArticleConceptLink) -> dict:
    return {
        "relationship": link.relationship,
        "pmid": link.pmid,
        "concept_id": link.concept_id,
        "source_field": link.source_field,
        "match_method": link.match_method,
        "confidence": link.confidence,
        "evidence_level": link.evidence_level,
    }


def _concept_key(concept: NormalizedConcept) -> tuple[str, str]:
    """Return the stable identity used to prevent duplicate summary concepts."""
    return concept.vocabulary, concept.concept_id


def _compact_concept_to_dict(concept: NormalizedConcept) -> dict:
    """Serialize only fields intended for the compact human-facing summary."""
    return {
        "preferred_label": concept.preferred_label,
        "vocabulary": concept.vocabulary,
        "concept_id": concept.concept_id,
        "concept_type": concept.concept_type,
        "supporting_article_count": len(set(concept.supporting_pmids)),
        "match_method": concept.match_method,
    }


def build_concept_summary(
    topic: str,
    profile: TopicProfile | None,
    concepts: ConceptNormalizationResult | None,
) -> dict:
    """Build the deterministic Phase B1.1 compact concept presentation.

    This derives a human-scale view from Phase-A/B1 artifacts without changing
    normalization, identifiers, links, provenance, or candidate retention.
    """
    normalized = tuple(concepts.normalized_concepts) if concepts else ()
    accepted = {candidate.term.casefold(): candidate for candidate in (profile.accepted_terms if profile else ())}
    normalized_topic = re.sub(r"\s+", " ", topic.strip().casefold())

    def candidate_for(concept: NormalizedConcept):
        return accepted.get(concept.original_term.casefold())

    eligible = [
        concept
        for concept in normalized
        if concept.concept_type != "unresolved" and candidate_for(concept) is not None
    ]

    core_candidates = []
    for concept in eligible:
        candidate = candidate_for(concept)
        exact_rxnorm_in_topic = (
            concept.vocabulary == "rxnorm"
            and concept.match_method == "exact"
            and re.sub(r"\s+", " ", concept.original_term.strip().casefold()) in normalized_topic
        )
        if candidate.direct_topic_overlap > 0 or exact_rxnorm_in_topic:
            core_candidates.append(concept)

    def ranking(concept: NormalizedConcept) -> tuple:
        candidate = candidate_for(concept)
        return (
            -candidate.score,
            -candidate.document_frequency,
            -len(set(concept.supporting_pmids)),
            concept.preferred_label.casefold(),
            concept.vocabulary,
            concept.concept_id,
        )

    core: list[NormalizedConcept] = []
    seen: set[tuple[str, str]] = set()
    for concept in sorted(core_candidates, key=ranking):
        if _concept_key(concept) not in seen:
            core.append(concept)
            seen.add(_concept_key(concept))
        if len(core) == 3:
            break

    related: list[NormalizedConcept] = []
    related_candidates = [
        concept
        for concept in eligible
        if len(set(concept.supporting_pmids)) >= 2 and _concept_key(concept) not in seen
    ]
    for concept in sorted(related_candidates, key=ranking):
        if _concept_key(concept) not in seen:
            related.append(concept)
            seen.add(_concept_key(concept))
        if len(related) == 5:
            break

    return {
        "core_concepts": [_compact_concept_to_dict(concept) for concept in core],
        "related_concepts": [_compact_concept_to_dict(concept) for concept in related],
        "total_concepts": len(normalized),
        "total_links": len(concepts.article_concept_links) if concepts else 0,
        "unresolved_count": sum(concept.concept_type == "unresolved" for concept in normalized),
        "rejected_candidate_count": len(profile.rejected_terms) if profile else 0,
    }


def build_snapshot(
    topic: str,
    query: str,
    fetched_at: datetime,
    ranked: list[RankedArticle] | None = None,
    profile: TopicProfile | None = None,
    concepts: ConceptNormalizationResult | None = None,
    articles: list[Article] | None = None,
    candidates: tuple[AssessedCandidate, ...] | None = None,
    clinical_target: ClinicalTarget | None = None,
    search_quality: SearchQualitySummary | None = None,
) -> dict:
    """Build the JSON snapshot payload."""
    if ranked is None:
        ranked = [RankedArticle(a, assess_article(a, fetched_at, topic)) for a in (articles or [])]
    ranked_by_pmid = {item.article.pmid: item for item in ranked}
    if candidates is not None:
        serialized_articles = []
        for candidate in candidates:
            ranked_item = ranked_by_pmid.get(candidate.article.pmid)
            payload = _article_to_dict(candidate.article)
            payload["assessment"] = _assessment_to_dict(
                ranked_item.assessment
                if ranked_item
                else assess_article(candidate.article, fetched_at, topic)
            )
            payload["clinical_relevance"] = _clinical_relevance_to_dict(candidate.relevance)
            if ranked_item:
                payload["ranking_audit"] = _ranking_audit(ranked_item)
                section, visible, reason = route_report_section(ranked_item)
                payload["structured_clinical_extraction"] = asdict(extract_clinical(candidate.article))
                payload["report_placement"] = {"section": section, "visible": visible, "reason": reason}
            serialized_articles.append(payload)
    else:
        serialized_articles = [_ranked_to_dict(r) for r in ranked]
    report_ranked = _report_ranked(ranked)
    snapshot = {
        "schema_version": "b4" if candidates is not None else "legacy",
        "topic": topic,
        "query": query,
        "fetched_at": fetched_at.isoformat(),
        "articles": serialized_articles,
        "visible_article_pmids": [item.article.pmid for item in report_ranked],
        "report_sections": {
            section: [item.article.pmid for item in report_ranked if route_report_section(item)[0] == section]
            for section in sorted({route_report_section(item)[0] for item in report_ranked})
        },
        "ranking_policy": "hard_gates > relevance_class > query_intent_compatibility > report_section > evidence_tier > study_design > comparator_suitability > extraction_completeness > bounded_sample_size > recency > pmid",
        "active_policy": load_policy(),
    }
    if clinical_target is not None:
        snapshot["clinical_target"] = _target_to_dict(clinical_target)
    if search_quality is not None:
        snapshot["search_quality"] = _quality_to_dict(search_quality)
    snapshot["discovered_terms"] = {
        "accepted": [_candidate_to_dict(c) for c in profile.accepted_terms] if profile else [],
        "rejected": [_candidate_to_dict(c) for c in profile.rejected_terms] if profile else [],
    }
    snapshot["normalized_concepts"] = [
        _concept_to_dict(concept) for concept in concepts.normalized_concepts
    ] if concepts else []
    snapshot["article_concept_links"] = [
        _concept_link_to_dict(link) for link in concepts.article_concept_links
    ] if concepts else []
    snapshot["concept_normalization_warnings"] = list(concepts.warnings) if concepts else []
    snapshot["concept_summary"] = build_concept_summary(topic, profile, concepts)
    return snapshot


def _compact_concept_markdown(concept: dict) -> list[str]:
    return [
        f"- **{concept['preferred_label']}**",
        f"  - Vocabulary and concept ID: {concept['vocabulary']} `{concept['concept_id']}`",
        f"  - Concept type: {concept['concept_type']}",
        f"  - Supporting articles: {concept['supporting_article_count']}",
        f"  - Match method: {concept['match_method']}",
    ]


def _concept_summary_markdown(
    topic: str,
    profile: TopicProfile | None,
    concepts: ConceptNormalizationResult | None,
) -> str:
    """Build the compact default Markdown concept presentation."""
    if concepts is None and profile is None:
        return ""
    summary = build_concept_summary(topic, profile, concepts)
    lines = ["## Medical concept summary", "", "## Discovered terms", ""]
    lines.append(
        f"{summary['total_concepts']} normalized concepts and {summary['total_links']} "
        "article-concept links were retained in the machine-readable audit data."
    )
    lines.extend(["", "### Core concepts", ""])
    if summary["core_concepts"]:
        for concept in summary["core_concepts"]:
            lines.extend(_compact_concept_markdown(concept) + [""])
    else:
        lines.extend(["No core concepts met the presentation criteria.", ""])
    lines.extend(["### Related concepts", ""])
    if summary["related_concepts"]:
        for concept in summary["related_concepts"]:
            lines.extend(_compact_concept_markdown(concept) + [""])
    else:
        lines.extend(["No related concepts met the presentation criteria.", ""])
    lines.append(f"**Unresolved concepts:** {summary['unresolved_count']}")
    lines.append("")
    if summary["rejected_candidate_count"]:
        lines.append(
            f"{summary['rejected_candidate_count']} additional candidates were rejected during quality filtering."
        )
        lines.append("")
    return "\n".join(lines)


def _discovered_terms_markdown(profile: TopicProfile | None) -> str:
    """Retained for compatibility; default reports use the compact summary."""
    if profile is None:
        return ""
    lines: list[str] = []
    lines.append("## Discovered terms")
    lines.append("")
    if not profile.accepted_terms and not profile.rejected_terms:
        lines.append("No candidate terms were discovered from MeSH headings or author keywords.")
        lines.append("")
        return "\n".join(lines)

    if profile.accepted_terms:
        lines.append("### Accepted")
        lines.append("")
        for c in profile.accepted_terms:
            lines.append(f"- **{c.term}** — accepted (score {c.score:.0f}/100, DF {c.document_frequency}, evidence {c.evidence_max}, source {c.source})")
            for reason in c.reasons:
                lines.append(f"  - Why: {reason}")
            lines.append("")
    if profile.rejected_terms:
        lines.append(
            f"{len(profile.rejected_terms)} additional candidates were rejected during quality filtering."
        )
        lines.append("")
    return "\n".join(lines)


def build_markdown_report(
    topic: str,
    fetched_at: datetime,
    ranked: list[RankedArticle] | None = None,
    profile: TopicProfile | None = None,
    concepts: ConceptNormalizationResult | None = None,
    articles: list[Article] | None = None,
    search_quality: SearchQualitySummary | None = None,
) -> str:
    """Build a human-readable Markdown report."""
    legacy_articles = ranked is None and articles is not None
    if ranked is None:
        ranked = [RankedArticle(a, assess_article(a, fetched_at, topic)) for a in (articles or [])]
    display_ranked = _report_ranked(ranked)
    lines: list[str] = []
    lines.append(f"# PubMed Report: {topic}")
    lines.append("")
    lines.append(f"**Fetch timestamp:** {fetched_at.isoformat()}")
    lines.append("")
    lines.append(f"**Articles:** {len(display_ranked)}")
    lines.append("")
    if any(item.assessment.study_assessment for item in ranked):
        lines.extend([
            "**Assessment scope:** Abstract/metadata-based evidence-strength triage from PubMed metadata and abstracts.",
            "",
            "This is not full-text appraisal, GRADE, a formal risk-of-bias assessment, or clinical advice.",
            "",
        ])
    if search_quality:
        total = (
            search_quality.total_result_count
            if search_quality.total_result_count is not None
            else "not available"
        )
        lines.extend(
            [
                "## Search quality",
                "",
                f"- **Original query:** {search_quality.query}",
                f"- **PubMed results:** {total}",
                f"- **Candidates fetched:** {search_quality.fetched_candidate_count} "
                f"(limit {search_quality.candidate_limit})",
                f"- **Included / excluded:** {search_quality.included_count} / {search_quality.excluded_count} "
                f"(report limit {search_quality.report_limit})",
                f"- **Direct / class-level / contextual / irrelevant:** "
                f"{search_quality.direct_count} / {search_quality.class_level_count} / "
                f"{search_quality.contextual_count} / {search_quality.irrelevant_count}",
                "",
            ]
        )
    lines.append("---")
    lines.append("")

    concept_summary = _concept_summary_markdown(topic, profile, concepts)
    if concept_summary:
        lines.append(concept_summary)
        lines.append("---")
        lines.append("")

    # Preserve the original article-only API as a flat report for callers that
    # have not opted into Phase-A sectioned ranking.
    if legacy_articles:
        for i, r in enumerate(ranked, start=1):
            article = r.article
            a = r.assessment
            lines.append(f"## {i}. {article.title}")
            lines.append("")
            lines.append(f"- **Publication date as listed by PubMed:** {article.publication_date_raw}")
            lines.append(f"- **Publication types:** {', '.join(article.publication_types)}")
            if article.doi:
                lines.append(f"- **DOI:** {article.doi}")
            if article.pubmed_url:
                lines.append(f"- **PubMed:** [Open in PubMed]({article.pubmed_url})")
            if article.abstract:
                lines.append("")
                lines.append(f"**Abstract:** {article.abstract}")
            lines.append("")
            lines.append("---")
            lines.append("")
        return "\n".join(lines)

    b2_mode = any(item.clinical_relevance for item in display_ranked)
    sections = (
        (
            ("key_evidence", "Key evidence"),
            ("early_safety_signals", "Early safety signals"),
            ("pharmacovigilance_signals", "Pharmacovigilance signals"),
            ("clinical_background_and_overview", "Clinical background and overview"),
            ("emerging_mechanisms_and_research_trends", "Emerging mechanisms and research trends"),
        )
        if b2_mode
        else tuple(
            {
                "key_evidence": "Key evidence",
                "important_updates": "Important updates",
                "exploratory_evidence": "Exploratory evidence",
            }.items()
        )
    )
    for section_key, section_label in sections:
        section_articles = [
            r for r in display_ranked if (route_report_section(r)[0] == section_key if b2_mode else r.assessment.section == section_key)
        ]
        if not section_articles:
            continue
        lines.append(f"## {section_label}")
        lines.append("")

        if b2_mode and section_key == "contextual":
            trend_articles = [
                r for r in section_articles
                if r.clinical_relevance and r.clinical_relevance.content_role in {"emerging_mechanism", "research_enabler"}
            ]
            standard_articles = [r for r in section_articles if r not in trend_articles]
            groups = (("Emerging mechanisms and research trends", trend_articles), (section_label, standard_articles))
        else:
            groups = ((section_label, section_articles),)
        for group_label, group_articles in groups:
            if group_label != section_label and group_articles:
                lines.append(f"### {group_label}")
                lines.append("")
            for i, r in enumerate(group_articles, start=1):
                article = r.article
                a = r.assessment
                lines.append(f"## {i}. {article.title}")
                lines.append("")
                lines.append(f"- **Evidence level:** {a.evidence_level_label}")
                if a.study_assessment:
                    study = a.study_assessment
                    lines.append(f"- **Study design:** {study.design_subtype}")
                    lines.append(f"- **Evidence strength:** {study.evidence_tier}")
                    lines.append(f"- **Population scope:** {study.population_scope}")
                    if study.sample_size is not None:
                        lines.append(f"- **Sample size:** {study.sample_size}")
                    elif study.sample_size_status != "reported":
                        lines.append("- **Sample size:** Not reported")
                    if study.comparator_text:
                        lines.append(f"- **Comparator:** {study.comparator_text}")
                    else:
                        lines.append("- **Comparator:** Not reported")
                    lines.append(f"- **Treatment duration:** {study.treatment_duration_text or 'Not reported'}")
                    if study.follow_up_text:
                        lines.append(f"- **Follow-up:** {study.follow_up_text}")
                    else:
                        lines.append("- **Follow-up:** Not reported")
                    if study.limitation_codes:
                        lines.append(f"- **Study limitations:** {', '.join(study.limitation_codes)}")
                if r.clinical_relevance:
                    lines.append(
                    f"- **Clinical relevance:** {r.clinical_relevance.relevance_class} "
                    f"({r.clinical_relevance.relevance_score}/100)"
                    )
                    lines.append(f"- **Content role:** {r.clinical_relevance.content_role}")
                    lines.append(f"- **Needs review:** {'yes' if r.clinical_relevance.needs_review else 'no'}")
                lines.append(f"- **Evidence score:** {a.evidence_score}/100")
                lines.append(f"- **Relevance score:** {a.relevance_score}/100")
                lines.append(f"- **Overall score:** {a.overall_score}/100")
                if article.publication_date_raw:
                    lines.append(
                    f"- **Publication date as listed by PubMed:** {article.publication_date_raw}"
                    )
                if article.electronic_publication_date:
                    lines.append(
                    f"- **Electronic publication date:** {article.electronic_publication_date.isoformat()}"
                    )
                if a.is_future_issue_dated:
                    lines.append("- **Status:** Future journal-issue date (scheduled, not yet published)")
                if a.is_electronic_only:
                    lines.append("- **Status:** Available electronically ahead of print")
                if article.publication_types:
                    lines.append(f"- **Publication types:** {', '.join(article.publication_types)}")
                if article.doi:
                    lines.append(f"- **DOI:** {article.doi}")
                if article.pubmed_url:
                    lines.append(f"- **PubMed:** [Open in PubMed]({article.pubmed_url})")
                if r.clinical_relevance:
                    lines.append(f"- **Why included:** {r.clinical_relevance.reason}")
                elif a.reasons:
                    lines.append(f"- **Why included:** {'; '.join(a.reasons)}")
                if a.limitations:
                    lines.append(f"- **Limitations:** {'; '.join(a.limitations)}")
                card = _clinical_card_data(r)
                lines.extend(["", "### Clinical evidence card", "", f"- **Population:** {card['population']}", f"- **Intervention:** {card['intervention']}", f"- **Comparator:** {card['comparator']}", f"- **Outcome:** {'; '.join(card['outcomes'])}", f"- **Effect:** {'; '.join(card['effects'])}", f"- **Safety:** {'; '.join(card['safety'])}", f"- **Limitations:** {'; '.join(card['limitations'])}"])
                if card["spans"]:
                    lines.extend(["", "<details>", "<summary>Supporting spans</summary>", "", *[f"- {span}" for span in card["spans"]], "", "</details>"])
                lines.extend(["", "<details>", "<summary>Abstract</summary>", "", card["abstract"], "", "</details>"])
                lines.extend(["", "<details>", "<summary>Audit details</summary>", "", f"- Placement: `{route_report_section(r)[0]}`", f"- Placement reason: {route_report_section(r)[2]}", f"- Relevance score: {a.relevance_score}/100", f"- Evidence score: {a.evidence_score}/100", f"- Overall score: {a.overall_score}/100", "", "</details>"])
                lines.append("")
                lines.append("---")
                lines.append("")

    return "\n".join(lines)


def _compact_concept_html(concept: dict) -> str:
    e = html.escape
    return (
        '<li class="concept-item">'
        f'<span class="concept-name">{e(concept["preferred_label"])}</span>'
        f'<dl><dt>Vocabulary and concept ID</dt><dd>{e(concept["vocabulary"])} '
        f'<code>{e(concept["concept_id"])}</code></dd>'
        f'<dt>Concept type</dt><dd>{e(concept["concept_type"])}</dd>'
        f'<dt>Supporting articles</dt><dd>{concept["supporting_article_count"]}</dd>'
        f'<dt>Match method</dt><dd>{e(concept["match_method"])}</dd></dl>'
        "</li>"
    )


def _technical_concept_item_html(
    concept: NormalizedConcept,
    link_count: int,
) -> str:
    """Render complete normalized-concept provenance plus aggregate link count."""
    e = html.escape
    pmids = ", ".join(concept.supporting_pmids) or "none"
    source_fields = ", ".join(concept.source_fields) or "none"
    return (
        '<li class="concept-item technical-concept-item">'
        f'<span class="concept-name">{e(concept.preferred_label)}</span>'
        f'<dl><dt>Vocabulary</dt><dd>{e(concept.vocabulary)}</dd>'
        f'<dt>Concept ID</dt><dd><code>{e(concept.concept_id)}</code></dd>'
        f'<dt>Original term</dt><dd>{e(concept.original_term)}</dd>'
        f'<dt>Concept type</dt><dd>{e(concept.concept_type)}</dd>'
        f'<dt>Match method</dt><dd>{e(concept.match_method)}</dd>'
        f'<dt>Confidence</dt><dd>{concept.confidence:.2f}</dd>'
        f'<dt>Supporting PMIDs</dt><dd>{e(pmids)}</dd>'
        f'<dt>Source fields</dt><dd>{e(source_fields)}</dd>'
        f'<dt>Article-concept links</dt><dd>{link_count}</dd></dl>'
        "</li>"
    )


def _concept_summary_html(
    topic: str,
    profile: TopicProfile | None,
    concepts: ConceptNormalizationResult | None,
) -> str:
    """Build compact visible concepts and collapsed technical audit details."""
    if concepts is None and profile is None:
        return ""
    e = html.escape
    summary = build_concept_summary(topic, profile, concepts)
    normalized = tuple(concepts.normalized_concepts) if concepts else ()
    links = tuple(concepts.article_concept_links) if concepts else ()
    link_counts: dict[str, int] = {}
    for link in links:
        link_counts[link.concept_id] = link_counts.get(link.concept_id, 0) + 1

    parts = [
        '<section class="normalized-concepts concept-summary">',
        '<h2>Medical concept summary</h2>',
        '<p class="legacy-section-label"><strong>Discovered terms</strong></p>',
    ]
    parts.append(
        f'<p>{summary["total_concepts"]} normalized concepts and {summary["total_links"]} '
        "article-concept links were retained in the machine-readable audit data.</p>"
    )
    for heading, key in (("Core concepts", "core_concepts"), ("Related concepts", "related_concepts")):
        parts.append(f"<h3>{heading}</h3>")
        if summary[key]:
            parts.append('<ul class="concept-list">')
            parts.extend(_compact_concept_html(concept) for concept in summary[key])
            parts.append("</ul>")
        else:
            parts.append(f'<p class="concept-empty">No {heading.lower()} met the presentation criteria.</p>')

    parts.append(f'<p class="concept-count"><strong>Unresolved concepts:</strong> {summary["unresolved_count"]}</p>')
    if summary["rejected_candidate_count"]:
        parts.append(
            f'<p class="rejected-count">{summary["rejected_candidate_count"]} additional candidates '
            "were rejected during quality filtering.</p>"
        )

    unresolved = [concept for concept in normalized if concept.concept_type == "unresolved"]
    parts.append('<details class="concept-details unresolved-details">')
    parts.append(f'<summary>Unresolved concept details ({len(unresolved)})</summary>')
    if unresolved:
        parts.append('<ul class="concept-list">')
        parts.extend(
            _technical_concept_item_html(concept, link_counts.get(concept.concept_id, 0))
            for concept in unresolved
        )
        parts.append("</ul>")
    else:
        parts.append("<p>No unresolved concepts.</p>")
    parts.append("</details>")

    parts.append('<details class="concept-details technical-concept-details">')
    parts.append("<summary>Technical concept details</summary>")
    for warning in concepts.warnings if concepts else ():
        parts.append(f'<p class="concept-warning"><strong>Warning:</strong> {e(warning)}</p>')
    if normalized:
        parts.append('<ul class="concept-list">')
        parts.extend(
            _technical_concept_item_html(concept, link_counts.get(concept.concept_id, 0))
            for concept in normalized
        )
        parts.append("</ul>")
    else:
        parts.append('<p class="concept-empty">No medical concepts were normalized.</p>')
    parts.append("</details>")
    parts.append("</section>")
    return "\n".join(parts)


def build_html_report(
    topic: str,
    fetched_at: datetime,
    ranked: list[RankedArticle] | None = None,
    profile: TopicProfile | None = None,
    concepts: ConceptNormalizationResult | None = None,
    articles: list[Article] | None = None,
    search_quality: SearchQualitySummary | None = None,
) -> str:
    """Build a polished, standalone HTML report directly from ranked data.

    All article content is escaped with :func:`html.escape`. The page uses
    inline CSS only — no external CDN, JavaScript, or frameworks.
    """
    if ranked is None:
        ranked = [RankedArticle(a, assess_article(a, fetched_at, topic)) for a in (articles or [])]
    display_ranked = _report_ranked(ranked)
    e = html.escape
    esc_topic = e(topic)
    esc_fetched_at = e(fetched_at.isoformat())
    article_count = len(display_ranked)
    has_b3_assessment = any(item.assessment.study_assessment for item in display_ranked)

    b2_mode = any(item.clinical_relevance for item in display_ranked)
    sections = (
        {
            "key_evidence": "Key evidence",
            "early_safety_signals": "Early safety signals",
            "pharmacovigilance_signals": "Pharmacovigilance signals",
            "clinical_background_and_overview": "Clinical background and overview",
            "emerging_mechanisms_and_research_trends": "Emerging mechanisms and research trends",
        }
        if b2_mode
        else {
            "key_evidence": "Key evidence",
            "important_updates": "Important updates",
            "exploratory_evidence": "Exploratory evidence",
        }
    )

    section_html_parts: list[str] = []
    for section_key, section_label in sections.items():
        section_articles = [
            r
            for r in display_ranked
            if (route_report_section(r)[0] == section_key if b2_mode else r.assessment.section == section_key)
        ]
        if not section_articles:
            continue

        cards: list[str] = []
        for i, r in enumerate(section_articles, start=1):
            article = r.article
            a = r.assessment

            esc_title = e(article.title)
            esc_date_raw = e(article.publication_date_raw)
            esc_types = e(", ".join(article.publication_types))
            esc_doi = e(article.doi)
            esc_url = e(article.pubmed_url)
            esc_abstract = e(article.abstract)
            esc_epub_date = (
                e(article.electronic_publication_date.isoformat())
                if article.electronic_publication_date
                else ""
            )

            meta_items: list[str] = []
            if r.clinical_relevance:
                meta_items.append(
                    f'<div class="meta-item"><span class="meta-label">Clinical relevance:</span> '
                    f'<span class="meta-value relevance-{e(r.clinical_relevance.relevance_class)}">'
                    f'{e(r.clinical_relevance.relevance_class.replace("_", " ").title())} '
                    f'({r.clinical_relevance.relevance_score}/100)</span></div>'
                )
            meta_items.append(
                f'<div class="meta-item"><span class="meta-label">Evidence level:</span> '
                f'<span class="meta-value">{e(a.evidence_level_label)}</span></div>'
            )
            if a.study_assessment:
                study = a.study_assessment
                meta_items.extend([
                    f'<div class="meta-item"><span class="meta-label">Study design:</span> <span class="meta-value">{e(study.design_subtype)}</span></div>',
                    f'<div class="meta-item"><span class="meta-label">Evidence strength:</span> <span class="meta-value">{e(_display_value(study.evidence_tier))}</span></div>',
                    f'<div class="meta-item"><span class="meta-label">Population scope:</span> <span class="meta-value">{e(_display_value(study.population_scope))}</span></div>',
                    f'<div class="meta-item"><span class="meta-label">Sample size:</span> <span class="meta-value">{e(str(study.sample_size) if study.sample_size is not None else "Not reported")}</span></div>',
                    f'<div class="meta-item"><span class="meta-label">Comparator:</span> <span class="meta-value">{e(study.comparator_text or "Not reported")}</span></div>',
                    f'<div class="meta-item"><span class="meta-label">Treatment duration:</span> <span class="meta-value">{e(study.treatment_duration_text or "Not reported")}</span></div>',
                ])
                if study.follow_up_text:
                    meta_items.append(
                        f'<div class="meta-item"><span class="meta-label">Follow-up:</span> <span class="meta-value">{e(study.follow_up_text)}</span></div>'
                    )
                else:
                    meta_items.append(
                        '<div class="meta-item"><span class="meta-label">Follow-up:</span> <span class="meta-value">Not reported</span></div>'
                    )
                if study.needs_review:
                    meta_items.append(
                        '<div class="meta-item"><span class="meta-label">Study review:</span> '
                        '<span class="meta-value status-future">Needs review</span></div>'
                    )
            meta_items.append(
                f'<div class="meta-item"><span class="meta-label">Evidence score:</span> '
                f'<span class="meta-value">{a.evidence_score}/100</span></div>'
            )
            meta_items.append(
                f'<div class="meta-item"><span class="meta-label">Relevance score:</span> '
                f'<span class="meta-value">{a.relevance_score}/100</span></div>'
            )
            meta_items.append(
                f'<div class="meta-item"><span class="meta-label">Overall score:</span> '
                f'<span class="meta-value">{a.overall_score}/100</span></div>'
            )
            if esc_date_raw:
                meta_items.append(
                    f'<div class="meta-item"><span class="meta-label">Publication date:</span> '
                    f'<span class="meta-value">{esc_date_raw}</span></div>'
                )
            if esc_epub_date:
                meta_items.append(
                    f'<div class="meta-item"><span class="meta-label">Electronic publication date:</span> '
                    f'<span class="meta-value">{esc_epub_date}</span></div>'
                )
            if a.is_future_issue_dated:
                meta_items.append(
                    '<div class="meta-item"><span class="meta-label">Status:</span> '
                    '<span class="meta-value status-future">Future journal-issue date '
                    "(scheduled, not yet published)</span></div>"
                )
            if a.is_electronic_only:
                meta_items.append(
                    '<div class="meta-item"><span class="meta-label">Status:</span> '
                    '<span class="meta-value status-epub">Available electronically ahead of print</span></div>'
                )
            if esc_types:
                meta_items.append(
                    f'<div class="meta-item"><span class="meta-label">Publication types:</span> '
                    f'<span class="meta-value">{esc_types}</span></div>'
                )
            if esc_doi:
                meta_items.append(
                    f'<div class="meta-item"><span class="meta-label">DOI:</span> '
                    f'<span class="meta-value">{esc_doi}</span></div>'
                )
            if esc_url:
                meta_items.append(
                    f'<div class="meta-item"><span class="meta-label">PubMed:</span> '
                    f'<a class="meta-link" href="{esc_url}" target="_blank" rel="noopener noreferrer">'
                    f"Open in PubMed</a></div>"
                )
            if r.clinical_relevance:
                meta_items.append(
                    f'<div class="meta-item"><span class="meta-label">Why included:</span> '
                    f'<span class="meta-value">{e(r.clinical_relevance.reason)}</span></div>'
                )
                meta_items.append(
                    f'<div class="meta-item"><span class="meta-label">Content role:</span> '
                    f'<span class="meta-value">{e(r.clinical_relevance.content_role)}</span></div>'
                )
            elif a.reasons:
                reasons_html = "".join(
                    f'<li class="reason-item">{e(reason)}</li>' for reason in a.reasons
                )
                meta_items.append(
                    f'<div class="meta-item"><span class="meta-label">Why included:</span> '
                    f'<ul class="reason-list">{reasons_html}</ul></div>'
                )
            if a.limitations:
                limitations_html = "".join(
                    f'<li class="limitation-item">{e(lim)}</li>' for lim in a.limitations
                )
                meta_items.append(
                    f'<div class="meta-item"><span class="meta-label">Limitations:</span> '
                    f'<ul class="limitation-list">{limitations_html}</ul></div>'
                )

            card = _clinical_card_data(r)
            clinical_html = (
                '<section class="clinical-card"><h3>Clinical evidence card</h3>'
                f'<dl><dt>Population</dt><dd>{e(card["population"])}</dd>'
                f'<dt>Intervention</dt><dd>{e(card["intervention"])}</dd>'
                f'<dt>Comparator</dt><dd>{e(card["comparator"])}</dd>'
                f'<dt>Outcome</dt><dd>{e("; ".join(card["outcomes"]))}</dd>'
                f'<dt>Effect</dt><dd>{e("; ".join(card["effects"]))}</dd>'
                f'<dt>Safety</dt><dd>{e("; ".join(card["safety"]))}</dd>'
                f'<dt>Limitations</dt><dd>{e("; ".join(card["limitations"]))}</dd></dl>'
                f'<details><summary>Supporting spans</summary><ul>{"".join(f"<li>{e(span)}</li>" for span in card["spans"]) or "<li>Not extractable</li>"}</ul></details></section>'
            )
            if esc_abstract:
                abstract_html = (
                    f'<details class="abstract"><summary class="abstract-label">Abstract:</summary>'
                    f'<p class="abstract-text">{esc_abstract}</p></details>'
                )
            else:
                abstract_html = (
                    '<div class="abstract abstract-missing">'
                    '<span class="abstract-label">Abstract:</span> '
                    '<p class="abstract-text">Abstract not available in PubMed</p>'
                    "</div>"
                )

            cards.append(
                f"""<article class="card">
  <h2 class="card-title"><span class="card-index">{i}.</span> {esc_title}</h2>
  <div class="card-meta">
    {chr(10).join(meta_items)}
  </div>
  {clinical_html}
  {abstract_html}
  {f'<details class="technical-audit"><summary>Study assessment audit</summary><p>Rule version: {e(a.study_assessment.rule_version)}; confidence: {e(a.study_assessment.confidence)}; signals: {e("; ".join(a.study_assessment.matched_signals))}</p></details>' if a.study_assessment else ''}
</article>"""
            )

        content = (
            f'<h2 class="section-heading">{e(section_label)}</h2>{"".join(cards)}'
        )
        if b2_mode and section_key == "clinical_background_and_overview":
            section_html_parts.append(
                f'<details class="report-section contextual-evidence" id="{section_key}">'
                f'<summary>{e(section_label)} ({len(cards)})</summary>{"".join(cards)}</details>'
            )
        else:
            section_html_parts.append(
                f'<section class="report-section" id="{section_key}">{content}</section>'
            )

    cards_html = "\n".join(section_html_parts)
    concepts_html = _concept_summary_html(topic, profile, concepts)
    quality_html = ""
    if search_quality:
        total = (
            str(search_quality.total_result_count)
            if search_quality.total_result_count is not None
            else "Not available"
        )
        quality_html = f'''<section class="search-quality">
  <h2>Search quality</h2>
  <dl>
    <dt>Original query</dt><dd>{e(search_quality.query)}</dd>
    <dt>PubMed results</dt><dd>{e(total)}</dd>
    <dt>Candidates fetched</dt><dd>{search_quality.fetched_candidate_count} (limit {search_quality.candidate_limit})</dd>
    <dt>Included / excluded</dt><dd>{search_quality.included_count} / {search_quality.excluded_count} (report limit {search_quality.report_limit})</dd>
    <dt>Direct / class-level / contextual / irrelevant</dt><dd>{search_quality.direct_count} / {search_quality.class_level_count} / {search_quality.contextual_count} / {search_quality.irrelevant_count}</dd>
  </dl>
</section>'''

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PubMed Report: {esc_topic}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                   "Helvetica Neue", Arial, sans-serif;
      background-color: #f4f6f8;
      color: #1a202c;
      line-height: 1.6;
      padding: 2rem 1rem;
    }}

    .container {{
      max-width: 900px;
      margin: 0 auto;
    }}

    header.report-header {{
      background: linear-gradient(135deg, #1a365d 0%, #2b6cb0 100%);
      color: #ffffff;
      border-radius: 12px;
      padding: 2rem 2.5rem;
      margin-bottom: 2rem;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
    }}

    header.report-header h1 {{
      font-size: 1.75rem;
      font-weight: 700;
      margin-bottom: 0.75rem;
      letter-spacing: -0.02em;
    }}

    .header-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 1.5rem;
      font-size: 0.95rem;
      opacity: 0.95;
    }}

    .header-meta span {{
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
    }}

    .header-meta .label {{
      font-weight: 600;
      text-transform: uppercase;
      font-size: 0.75rem;
      letter-spacing: 0.05em;
      opacity: 0.8;
    }}

    .scope-notice {{
      margin: 0 0 1rem;
      font-size: 0.92rem;
      opacity: 0.94;
    }}

    .report-section {{
      margin-bottom: 2.5rem;
    }}

    .search-quality {{ background: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px;
      padding: 1.25rem 1.5rem; margin-bottom: 2rem; }}
    .search-quality h2 {{ color: #1a365d; margin-bottom: 0.75rem; }}
    .search-quality dl {{ display: grid; grid-template-columns: 14rem 1fr; gap: 0.3rem 1rem; }}
    .search-quality dt {{ font-weight: 600; color: #4a5568; }}
    .contextual-evidence > summary {{ cursor: pointer; color: #1a365d; font-weight: 700;
      font-size: 1.2rem; margin-bottom: 1rem; }}

    .section-heading {{
      font-size: 1.4rem;
      font-weight: 700;
      color: #1a365d;
      margin-bottom: 1rem;
      padding-bottom: 0.5rem;
      border-bottom: 2px solid #e2e8f0;
    }}

    .card {{
      background: #ffffff;
      border: 1px solid #e2e8f0;
      border-radius: 10px;
      padding: 1.75rem 2rem;
      margin-bottom: 1.5rem;
      box-shadow: 0 2px 6px rgba(0, 0, 0, 0.06);
      transition: box-shadow 0.2s ease;
    }}

    .card:hover {{
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
    }}

    .card-title {{
      font-size: 1.2rem;
      font-weight: 600;
      color: #1a365d;
      margin-bottom: 1rem;
      line-height: 1.4;
    }}

    .card-index {{
      color: #718096;
      font-weight: 500;
      margin-right: 0.25rem;
    }}

    .card-meta {{
      display: flex;
      flex-direction: column;
      gap: 0.4rem;
      margin-bottom: 1rem;
    }}

    .meta-item {{
      font-size: 0.92rem;
    }}

    .meta-label {{
      font-weight: 600;
      color: #4a5568;
      margin-right: 0.4rem;
    }}

    .meta-value {{
      color: #2d3748;
    }}

    .meta-link {{
      color: #2b6cb0;
      text-decoration: none;
      font-weight: 500;
    }}

    .meta-link:hover {{
      text-decoration: underline;
    }}

    .status-future {{
      color: #c05621;
      font-weight: 600;
    }}

    .status-epub {{
      color: #2b6cb0;
      font-weight: 600;
    }}

    .reason-list, .limitation-list {{
      margin: 0.25rem 0 0 1.25rem;
      padding: 0;
    }}

    .reason-item, .limitation-item {{
      font-size: 0.88rem;
      color: #4a5568;
    }}

    .abstract {{
      background-color: #f7fafc;
      border-left: 4px solid #2b6cb0;
      border-radius: 0 6px 6px 0;
      padding: 1rem 1.25rem;
    }}

    .abstract-missing {{
      border-left-color: #a0aec0;
      background-color: #f7fafc;
    }}

    .abstract-label {{
      font-weight: 600;
      color: #2b6cb0;
      display: block;
      margin-bottom: 0.4rem;
      font-size: 0.85rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}

    .abstract-text {{
      color: #2d3748;
      font-size: 0.95rem;
    }}

    .clinical-card {{ margin: 1rem 0; padding: 1rem 1.25rem; background: #f8fafc;
      border: 1px solid #dbe4ee; border-radius: 8px; }}
    .clinical-card h3 {{ color: #1a365d; margin-bottom: .6rem; font-size: 1rem; }}
    .clinical-card dl {{ display: grid; grid-template-columns: 10rem 1fr; gap: .35rem .8rem; }}
    .clinical-card dt {{ font-weight: 700; color: #4a5568; }}
    .clinical-card dd {{ margin: 0; color: #2d3748; }}
    .clinical-card summary, .abstract summary {{ cursor: pointer; }}

    .discovered-terms {{
      background: #ffffff;
      border: 1px solid #e2e8f0;
      border-radius: 10px;
      padding: 1.75rem 2rem;
      margin-bottom: 2rem;
      box-shadow: 0 2px 6px rgba(0, 0, 0, 0.06);
    }}

    .discovered-terms h2 {{
      font-size: 1.3rem;
      font-weight: 700;
      color: #1a365d;
      margin-bottom: 1rem;
    }}

    .discovered-terms h3 {{
      font-size: 1.05rem;
      font-weight: 600;
      color: #2d3748;
      margin: 1rem 0 0.5rem;
    }}

    .term-list {{
      list-style: none;
      padding: 0;
      margin: 0;
    }}

    .term-item {{
      padding: 0.5rem 0;
      border-bottom: 1px solid #edf2f7;
    }}

    .term-item:last-child {{
      border-bottom: none;
    }}

    .term-name {{
      font-weight: 600;
      color: #2d3748;
    }}

    .term-badge {{
      display: inline-block;
      font-size: 0.75rem;
      font-weight: 600;
      padding: 0.1rem 0.5rem;
      border-radius: 9999px;
      margin-left: 0.5rem;
    }}

    .term-badge.accepted {{
      background-color: #c6f6d5;
      color: #22543d;
    }}

    .term-badge.rejected {{
      background-color: #fed7d7;
      color: #742a2a;
    }}

    .term-meta {{
      font-size: 0.85rem;
      color: #718096;
      margin-left: 0.5rem;
    }}

    .term-reasons {{
      margin: 0.25rem 0 0 1.25rem;
      padding: 0;
    }}

    .term-reason {{
      font-size: 0.85rem;
      color: #4a5568;
    }}

    .discovered-empty {{
      color: #718096;
      font-size: 0.95rem;
    }}

    .normalized-concepts {{
      background: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px;
      padding: 1.75rem 2rem; margin-bottom: 2rem;
      box-shadow: 0 2px 6px rgba(0, 0, 0, 0.06);
    }}
    .normalized-concepts h2 {{ color: #1a365d; margin-bottom: 1rem; }}
    .normalized-concepts h3 {{ color: #2d3748; margin: 1rem 0 0.5rem; }}
    .concept-list {{ list-style: none; }}
    .concept-item {{ padding: 0.75rem 0; border-bottom: 1px solid #edf2f7; }}
    .concept-name {{ font-weight: 700; color: #2d3748; }}
    .concept-item dl {{ display: grid; grid-template-columns: 13rem 1fr; gap: 0.2rem 1rem; }}
    .concept-item dt {{ font-weight: 600; color: #4a5568; }}
    .concept-warning {{ color: #9c4221; margin-bottom: 0.75rem; }}
    .concept-count, .rejected-count {{ margin-top: 0.75rem; }}
    .concept-details {{ margin-top: 1rem; border-top: 1px solid #e2e8f0; padding-top: 0.75rem; }}
    .concept-details summary {{ cursor: pointer; font-weight: 600; color: #2b6cb0; }}
    .concept-details[open] summary {{ margin-bottom: 0.75rem; }}

    footer.report-footer {{
      text-align: center;
      color: #718096;
      font-size: 0.85rem;
      margin-top: 2rem;
      padding-top: 1rem;
      border-top: 1px solid #e2e8f0;
    }}

    @media (max-width: 600px) {{
      body {{ padding: 1rem 0.5rem; }}
      header.report-header {{ padding: 1.5rem; }}
      .card {{ padding: 1.25rem 1.5rem; }}
      .header-meta {{ flex-direction: column; gap: 0.5rem; }}
      .clinical-card dl {{ display: block; }}
      .clinical-card dt {{ margin-top: .5rem; }}
    }}
  </style>
</head>
<body>
  <div class="container">
    <header class="report-header">
      <h1>PubMed Report: {esc_topic}</h1>
      {('<p class="scope-notice">Abstract/metadata-based evidence-strength triage from PubMed metadata and abstracts; not full-text appraisal, GRADE, formal risk-of-bias assessment, or clinical advice.</p>' if has_b3_assessment else '')}
      <div class="header-meta">
        <span><span class="label">Fetched</span> {esc_fetched_at}</span>
        <span><span class="label">Articles</span> {article_count}</span>
      </div>
    </header>

    {quality_html}

    {concepts_html}

    {cards_html}

    <footer class="report-footer">
      Generated locally by Medical Evidence Radar &middot; {esc_fetched_at}
    </footer>
  </div>
</body>
</html>
"""


def _timestamp_str(dt: datetime) -> str:
    """Format a datetime for use in filenames (safe for all filesystems)."""
    return dt.strftime("%Y%m%d_%H%M%S")


def _query_slug(query: str) -> str:
    """Create a readable, filesystem-safe filename stem from a user query.

    Unicode letters (including Persian text) are retained. Windows-reserved
    filename characters and punctuation are replaced/removed, and an empty
    result falls back to ``query``.
    """
    normalized = unicodedata.normalize("NFKC", query).strip().lower()
    normalized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", normalized)
    normalized = re.sub(r"[^\w\s-]", "", normalized, flags=re.UNICODE)
    slug = re.sub(r"[\s_-]+", "_", normalized).strip("._-")
    if not slug or slug.upper() in {"CON", "PRN", "AUX", "NUL"}:
        return "query"
    if len(slug) > MAX_QUERY_SLUG_LENGTH:
        digest = hashlib.sha256(query.encode("utf-8")).hexdigest()[:12]
        slug = f"{slug[:MAX_QUERY_SLUG_LENGTH - len(digest) - 1].rstrip('._-')}_{digest}"
    return slug


def _path_for_output(
    output_dir: Path,
    extension: str,
    fetched_at: datetime,
    query: str | None,
) -> Path:
    """Return a query-named path, adding a timestamp only on collision."""
    if query is None:
        return output_dir / f"pubmed_{_timestamp_str(fetched_at)}.{extension}"

    base = output_dir / f"{_query_slug(query)}.{extension}"
    if not base.exists():
        return base
    return output_dir / f"{_query_slug(query)}_{_timestamp_str(fetched_at)}.{extension}"


def save_snapshot(
    snapshot: dict,
    output_dir: Path = DEFAULT_JSON_DIR,
    fetched_at: datetime | None = None,
    query: str | None = None,
) -> Path:
    """Write the JSON snapshot to a query-named file and return its path."""
    fetched_at = fetched_at or datetime.now()
    output_dir.mkdir(parents=True, exist_ok=True)
    path = _path_for_output(output_dir, "json", fetched_at, query)
    path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def save_markdown_report(
    markdown: str,
    output_dir: Path = DEFAULT_MD_DIR,
    fetched_at: datetime | None = None,
    query: str | None = None,
) -> Path:
    """Write the Markdown report to a query-named file and return its path."""
    fetched_at = fetched_at or datetime.now()
    output_dir.mkdir(parents=True, exist_ok=True)
    path = _path_for_output(output_dir, "md", fetched_at, query)
    path.write_text(markdown, encoding="utf-8")
    return path


def save_html_report(
    html_report: str,
    output_dir: Path = DEFAULT_HTML_DIR,
    fetched_at: datetime | None = None,
    query: str | None = None,
) -> Path:
    """Write the HTML report to a query-named file and return its path."""
    fetched_at = fetched_at or datetime.now()
    output_dir.mkdir(parents=True, exist_ok=True)
    path = _path_for_output(output_dir, "html", fetched_at, query)
    path.write_text(html_report, encoding="utf-8")
    return path


def concept_path_for_topic(topic: str, output_dir: Path = DEFAULT_CONCEPT_DIR) -> Path:
    return output_dir / f"{_query_slug(topic)}.json"


def save_concept_file(
    topic: str,
    concepts: ConceptNormalizationResult,
    output_dir: Path = DEFAULT_CONCEPT_DIR,
) -> Path:
    """Save the latest per-topic Phase B1 concept artifact."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = concept_path_for_topic(topic, output_dir)
    payload = {
        "topic": topic,
        "normalized_concepts": [_concept_to_dict(item) for item in concepts.normalized_concepts],
        "article_concept_links": [_concept_link_to_dict(item) for item in concepts.article_concept_links],
        "warnings": list(concepts.warnings),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
