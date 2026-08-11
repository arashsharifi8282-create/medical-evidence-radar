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