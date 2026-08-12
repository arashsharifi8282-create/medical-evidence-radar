"""Retrieval metadata retained for transparent PubMed search auditing."""

from dataclasses import dataclass

from app.models.article import Article


@dataclass(frozen=True)
class PubMedSearchResult:
    """The ordered PMID page returned by ESearch plus its full result count."""

    pmids: tuple[str, ...]
    total_count: int | None


@dataclass(frozen=True)
class RetrievalBatch:
    """A normalized, de-duplicated candidate batch."""

    query: str
    candidate_limit: int
    total_count: int | None
    articles: tuple[Article, ...]
    duplicate_pmids: tuple[str, ...] = ()
