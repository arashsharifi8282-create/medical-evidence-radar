"""Explainable medical concept normalization models for Phase B1."""

from dataclasses import dataclass


@dataclass(frozen=True)
class NormalizedConcept:
    """A source-backed MeSH/RxNorm concept or a preserved unresolved term."""

    concept_id: str
    vocabulary: str  # "mesh" | "rxnorm"
    preferred_label: str
    original_term: str
    concept_type: str  # "drug" | "mesh_concept" | "unresolved"
    match_method: str  # "exact" | "normalized" | "approximate" | "source_metadata"
    confidence: float
    supporting_pmids: tuple[str, ...]
    source_fields: tuple[str, ...]  # mesh | author_keyword | title | abstract


@dataclass(frozen=True)
class ArticleConceptLink:
    """The only relationship emitted by Phase B1."""

    relationship: str
    pmid: str
    concept_id: str
    source_field: str
    match_method: str
    confidence: float
    evidence_level: str


@dataclass(frozen=True)
class ConceptNormalizationResult:
    """Concepts, safe article links, and non-fatal normalization warnings."""

    normalized_concepts: tuple[NormalizedConcept, ...]
    article_concept_links: tuple[ArticleConceptLink, ...]
    warnings: tuple[str, ...] = ()