"""Topic profile data model for discovered terms."""

from dataclasses import dataclass
from datetime import datetime

from app.models.assessment import EvidenceLevel


@dataclass(frozen=True)
class CandidateTerm:
    """A candidate term discovered from MeSH headings or author keywords."""

    term: str
    source: str                    # "mesh" | "keyword"
    document_frequency: int        # distinct articles containing this term
    evidence_max: EvidenceLevel    # highest evidence level among supporting articles
    recency_days: int              # days since most recent supporting article
    direct_topic_overlap: float    # 0..1 lexical overlap with original topic
    supporting_articles: tuple[str, ...]  # PMIDs
    score: float
    reasons: tuple[str, ...]
    accepted: bool


@dataclass(frozen=True)
class TopicProfile:
    """Persisted topic profile for a single free-text topic."""

    topic: str
    query: str                     # original free-text (primary ATM query, unchanged)
    run_at: datetime
    accepted_terms: tuple[CandidateTerm, ...]
    rejected_terms: tuple[CandidateTerm, ...]