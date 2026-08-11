"""Explainable, non-clinical MeSH and RxNorm concept normalization."""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict

from app.models.concept import ArticleConceptLink, ConceptNormalizationResult, NormalizedConcept
from app.models.topic_profile import TopicProfile
from app.models.assessment import RankedArticle
from app.sources.rxnorm.client import RxNormClient

ARTICLE_MENTIONS_CONCEPT = "ARTICLE_MENTIONS_CONCEPT"
_SOURCE_ORDER = ("mesh", "author_keyword", "title", "abstract")


def normalize_medical_concepts(
    ranked: list[RankedArticle],
    profile: TopicProfile | None,
    rxnorm_client: RxNormClient | None,
) -> ConceptNormalizationResult:
    """Identify source-backed concepts without inferring clinical relationships."""
    concepts: list[NormalizedConcept] = []
    links: list[ArticleConceptLink] = []
    warnings: list[str] = []

    mesh_occurrences: dict[str, dict] = {}
    for ranked_article in ranked:
        article = ranked_article.article
        for descriptor in article.mesh_descriptors:
            if not descriptor.ui:
                continue
            entry = mesh_occurrences.setdefault(
                descriptor.ui,
                {"label": descriptor.text, "pmids": set()},
            )
            entry["pmids"].add(article.pmid)
            links.append(
                _link(
                    ranked_article,
                    descriptor.ui,
                    "mesh",
                    "source_metadata",
                    1.0,
                )
            )

    for ui, entry in mesh_occurrences.items():
        concepts.append(
            NormalizedConcept(
                concept_id=ui,
                vocabulary="mesh",
                preferred_label=entry["label"],
                original_term=entry["label"],
                concept_type="mesh_concept",
                match_method="source_metadata",
                confidence=1.0,
                supporting_pmids=tuple(sorted(entry["pmids"])),
                source_fields=("mesh",),
            )
        )

    for candidate in profile.accepted_terms if profile else ():
        occurrences = _term_occurrences(candidate.term, ranked, set(candidate.supporting_articles))
        try:
            if rxnorm_client is None:
                raise RuntimeError("RxNorm lookup was not configured")
            matches = rxnorm_client.lookup(candidate.term)
        except Exception as exc:  # report generation must survive all transport/API failures
            matches = ()
            warnings.append(f"RxNorm lookup failed for {candidate.term!r}: {exc}")

        if not matches:
            unresolved = _unresolved_concept(candidate.term, occurrences)
            concepts.append(unresolved)
            links.extend(_links_for_occurrences(ranked, unresolved, occurrences))
            continue

        for match in matches:
            confidence = 1.0 if match.match_method == "exact" else 0.9
            concept = NormalizedConcept(
                concept_id=match.rxcui,
                vocabulary="rxnorm",
                preferred_label=match.name,
                original_term=candidate.term,
                concept_type="drug",
                match_method=match.match_method,
                confidence=confidence,
                supporting_pmids=tuple(sorted(occurrences)),
                source_fields=_source_fields(occurrences),
            )
            concepts.append(concept)
            links.extend(_links_for_occurrences(ranked, concept, occurrences))

    return ConceptNormalizationResult(
        normalized_concepts=tuple(_merge_concepts(concepts)),
        article_concept_links=tuple(_deduplicate_links(links)),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _term_occurrences(
    term: str,
    ranked: list[RankedArticle],
    supporting_pmids: set[str],
) -> dict[str, set[str]]:
    normalized_term = _normalize(term)
    occurrences: dict[str, set[str]] = defaultdict(set)
    for ranked_article in ranked:
        article = ranked_article.article
        if article.pmid not in supporting_pmids:
            continue
        if any(_normalize(item) == normalized_term for item in article.mesh_headings):
            occurrences[article.pmid].add("mesh")
        if any(_normalize(item) == normalized_term for item in article.keywords):
            occurrences[article.pmid].add("author_keyword")
        if normalized_term and normalized_term in _normalize(article.title):
            occurrences[article.pmid].add("title")
        if normalized_term and normalized_term in _normalize(article.abstract):
            occurrences[article.pmid].add("abstract")
        if article.pmid not in occurrences:
            occurrences[article.pmid].add(
                "mesh" if candidate_source_is_mesh(term, article.mesh_headings) else "author_keyword"
            )
    return occurrences


def candidate_source_is_mesh(term: str, headings: tuple[str, ...]) -> bool:
    return any(_normalize(item) == _normalize(term) for item in headings)


def _unresolved_concept(term: str, occurrences: dict[str, set[str]]) -> NormalizedConcept:
    digest = hashlib.sha256(_normalize(term).encode("utf-8")).hexdigest()[:16]
    return NormalizedConcept(
        concept_id=f"unresolved:{digest}",
        vocabulary="rxnorm",
        preferred_label=term,
        original_term=term,
        concept_type="unresolved",
        match_method="approximate",
        confidence=0.0,
        supporting_pmids=tuple(sorted(occurrences)),
        source_fields=_source_fields(occurrences),
    )


def _source_fields(occurrences: dict[str, set[str]]) -> tuple[str, ...]:
    present = {field for fields in occurrences.values() for field in fields}
    return tuple(field for field in _SOURCE_ORDER if field in present)


def _links_for_occurrences(
    ranked: list[RankedArticle],
    concept: NormalizedConcept,
    occurrences: dict[str, set[str]],
) -> list[ArticleConceptLink]:
    by_pmid = {item.article.pmid: item for item in ranked}
    return [
        _link(
            by_pmid[pmid],
            concept.concept_id,
            source_field,
            concept.match_method,
            concept.confidence,
        )
        for pmid, source_fields in occurrences.items()
        if pmid in by_pmid
        for source_field in _SOURCE_ORDER
        if source_field in source_fields
    ]


def _link(
    ranked_article: RankedArticle,
    concept_id: str,
    source_field: str,
    match_method: str,
    confidence: float,
) -> ArticleConceptLink:
    return ArticleConceptLink(
        relationship=ARTICLE_MENTIONS_CONCEPT,
        pmid=ranked_article.article.pmid,
        concept_id=concept_id,
        source_field=source_field,
        match_method=match_method,
        confidence=confidence,
        evidence_level=ranked_article.assessment.evidence_level,
    )


def _merge_concepts(concepts: list[NormalizedConcept]) -> list[NormalizedConcept]:
    grouped: dict[tuple[str, str, str], list[NormalizedConcept]] = defaultdict(list)
    for concept in concepts:
        grouped[(concept.vocabulary, concept.concept_id, concept.original_term)].append(concept)

    merged: list[NormalizedConcept] = []
    for group in grouped.values():
        first = group[0]
        merged.append(
            NormalizedConcept(
                concept_id=first.concept_id,
                vocabulary=first.vocabulary,
                preferred_label=first.preferred_label,
                original_term=first.original_term,
                concept_type=first.concept_type,
                match_method=first.match_method,
                confidence=max(item.confidence for item in group),
                supporting_pmids=tuple(sorted({p for item in group for p in item.supporting_pmids})),
                source_fields=tuple(
                    field
                    for field in _SOURCE_ORDER
                    if any(field in item.source_fields for item in group)
                ),
            )
        )
    return sorted(merged, key=lambda item: (item.vocabulary, item.preferred_label.casefold(), item.concept_id))


def _deduplicate_links(links: list[ArticleConceptLink]) -> list[ArticleConceptLink]:
    unique = {
        (link.relationship, link.pmid, link.concept_id, link.source_field): link
        for link in links
    }
    return sorted(unique.values(), key=lambda item: (item.pmid, item.concept_id, item.source_field))


def _normalize(term: str) -> str:
    return re.sub(r"\s+", " ", term.strip().casefold())