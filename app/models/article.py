"""Normalized article data model shared across all sources."""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class MeshDescriptor:
    """A MeSH descriptor exactly as supplied by PubMed EFetch metadata."""

    text: str
    ui: str
    major_topic: bool
    supporting_pmid: str


@dataclass(frozen=True)
class AbstractSection:
    """One labelled PubMed structured-abstract segment, preserved verbatim."""

    label: str
    text: str


@dataclass(frozen=True)
class PublicationIntegrityRelation:
    """One structured PubMed ``CommentsCorrections`` relationship.

    Values are retained conservatively: a missing related identifier remains
    ``None`` and an unknown ``RefType`` is normalized to ``unknown`` rather
    than inferred from citation text.
    """

    normalized_relation: str
    raw_ref_type: str
    related_pmid: str | None
    related_doi: str | None
    source_text: str
    source_field: str = "CommentsCorrections"
    rule_id: str = "PUBMED_COMMENTS_CORRECTIONS"
    rule_version: str = "1.0"


@dataclass(frozen=True)
class Article:
    """A single normalized article record.

    Fields are deliberately minimal: everything needed to display a search
    result, nothing more. ``source`` marks provenance for future multi-source
    support.

    ``publication_date`` is the journal-issue/print date (may be in the future
    for a scheduled issue). ``electronic_publication_date`` is when the article
    was first posted electronically (epub ahead of print).
    """

    pmid: str
    title: str
    abstract: str
    authors: tuple[str, ...] = ()
    journal: str = ""
    publication_date: date | None = None
    publication_date_raw: str = ""
    electronic_publication_date: date | None = None
    is_epub_ahead_of_print: bool = False
    publication_types: tuple[str, ...] = ()
    doi: str = ""
    pubmed_url: str = ""
    source: str = "pubmed"
    mesh_headings: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    mesh_descriptors: tuple[MeshDescriptor, ...] = ()
    abstract_sections: tuple[AbstractSection, ...] = ()
    integrity_relations: tuple[PublicationIntegrityRelation, ...] = ()
