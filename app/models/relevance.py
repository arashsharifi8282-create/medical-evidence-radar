"""Explainable clinical-relevance models for Phase B2."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from app.models.article import Article
from app.models.retrieval import RetrievalBatch

if TYPE_CHECKING:
    from app.models.assessment import RankedArticle


@dataclass(frozen=True)
class ConfirmedDrugClass:
    """A parent class returned by an approved official RxClass vocabulary."""

    class_id: str
    preferred_label: str
    vocabulary: str
    relationship: str
    source_rxcui: str
    synonyms: tuple[str, ...] = ()


@dataclass(frozen=True)
class ClinicalTarget:
    """The intervention and condition against which candidates are assessed."""

    intervention_term: str
    condition_term: str
    extraction_method: str
    intervention_rxcuis: tuple[str, ...] = ()
    intervention_labels: tuple[str, ...] = ()
    condition_mesh_uis: tuple[str, ...] = ()
    condition_labels: tuple[str, ...] = ()
    confirmed_classes: tuple[ConfirmedDrugClass, ...] = ()
    warnings: tuple[str, ...] = ()
    query_intents: tuple[str, ...] = ()
    human_clinical_query: bool = True
    intervention_logic: str = "OR"
    target_interventions: tuple[str, ...] = ()


@dataclass(frozen=True)
class RelevanceSignal:
    """One source-field match that contributed to a relevance assessment."""

    role: str  # intervention | intervention_class | condition
    matched_text: str
    normalized_label: str
    concept_id: str
    vocabulary: str
    source_field: str  # title | mesh_major | mesh | author_keyword | abstract | abstract_<section>
    weight: int
    relationship_source: str = ""


@dataclass(frozen=True)
class ClinicalRelevanceAssessment:
    """Deterministic inclusion assessment for one PubMed candidate."""

    pmid: str
    relevance_class: str  # direct | class_level | contextual | irrelevant
    relevance_score: int
    intervention_signals: tuple[RelevanceSignal, ...]
    condition_signals: tuple[RelevanceSignal, ...]
    decision: str
    reason: str
    assessed_at: datetime
    query_intents: tuple[str, ...] = ()
    article_intents: tuple[str, ...] = ()
    article_focus: str = "unknown"
    coherence_status: str = "unknown"
    content_role: str = "clinical_evidence"
    population_scope: str = "unknown"
    needs_review: bool = False
    review_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class AssessedCandidate:
    """A candidate retained for audit, whether included or excluded."""

    article: Article
    relevance: ClinicalRelevanceAssessment


@dataclass(frozen=True)
class SearchQualitySummary:
    """Compact accounting of candidate retrieval and report selection."""

    query: str
    total_result_count: int | None
    candidate_limit: int
    report_limit: int
    raw_candidate_count: int
    fetched_candidate_count: int
    duplicate_count: int
    duplicate_pmids: tuple[str, ...]
    included_count: int
    excluded_count: int
    direct_count: int
    class_level_count: int
    contextual_count: int
    irrelevant_count: int
    excluded_irrelevant_count: int
    excluded_report_limit_count: int


@dataclass(frozen=True)
class RelevanceRun:
    """Complete Phase B2 output used by persistence and downstream phases."""

    retrieval: RetrievalBatch
    target: ClinicalTarget
    candidates: tuple[AssessedCandidate, ...]
    ranked: tuple[RankedArticle, ...]
    profile_ranked: tuple[RankedArticle, ...]
    search_quality: SearchQualitySummary
