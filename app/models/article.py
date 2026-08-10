"""Normalized article data model shared across all sources."""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Article:
    """A single normalized article record.

    Fields are deliberately minimal: everything needed to display a search
    result, nothing more. ``source`` marks provenance for future multi-source
    support.
    """

    pmid: str
    title: str
    abstract: str
    authors: tuple[str, ...] = ()
    journal: str = ""
    publication_date: date | None = None
    publication_date_raw: str = ""
    publication_types: tuple[str, ...] = ()
    doi: str = ""
    pubmed_url: str = ""
    source: str = "pubmed"