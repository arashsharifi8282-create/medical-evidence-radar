"""Automatic topic-term discovery from MeSH headings and author keywords.

This module is pure: it takes ranked articles plus a fetch timestamp and returns
a :class:`TopicProfile` with accepted and rejected candidate terms. No network
calls are made here.

Only MeSH headings and author keywords are independent candidates in v1.
Title/abstract text only boosts the score of an already-present candidate.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from app.models.assessment import RankedArticle
from app.models.topic_profile import CandidateTerm, TopicProfile

# Fixed constants for v1 (no CLI/env configuration).
MIN_DF = 2
SCORE_ACCEPT_THRESHOLD = 60.0
TITLE_BOOST = 5.0
ABSTRACT_BOOST = 3.0
BOOST_CAP = 5.0  # title/abstract boost can never push a sub-threshold term past acceptance alone

# Generic medical stopwords that should never be accepted as topic terms.
_STOPWORDS = {
    "humans", "human", "female", "male", "adult", "child", "children",
    "aged", "middle aged", "young adult", "adolescent", "infant", "infants",
    "animals", "animal", "mice", "rats", "rat", "mouse",
    "drug therapy", "therapeutic use", "treatment outcome", "drug effects",
    "metabolism", "physiology", "pathology", "etiology", "diagnosis",
    "therapy", "prevention and control", "epidemiology", "complications",
    "methods", "standards", "statistics and numerical data",
    "journal article", "review", "systematic review", "meta-analysis",
    "randomized controlled trial", "observational study", "clinical trial",
    "comparative study", "evaluation study", "validation study",
    "english abstract", "pubmed", "medline",
}

# Evidence-level ordering for evidence_max.
_EVIDENCE_ORDER = {
    "guideline": 6,
    "systematic_review": 5,
    "randomized_trial": 4,
    "observational": 3,
    "narrative_review": 2,
    "other": 1,
}

_EVIDENCE_BONUS = {
    "guideline": 100.0,
    "systematic_review": 90.0,
    "randomized_trial": 80.0,
    "observational": 60.0,
    "narrative_review": 40.0,
    "other": 20.0,
}


def _normalize_term(term: str) -> str:
    """Normalize a term for deduplication (lowercase, collapse whitespace)."""
    return re.sub(r"\s+", " ", term.strip().lower())


def _tokenize(text: str) -> set[str]:
    """Lowercase, strip punctuation, and return a set of tokens."""
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _direct_topic_overlap(term: str, topic: str) -> float:
    """Compute lexical overlap (0..1) between a term and the free-text topic."""
    term_tokens = _tokenize(term)
    topic_tokens = _tokenize(topic)
    if not term_tokens or not topic_tokens:
        return 0.0
    overlap = len(term_tokens & topic_tokens)
    return overlap / len(term_tokens)


def _recency_bonus(days: int) -> float:
    """Map recency (days) to a 0..100 bonus."""
    if days <= 90:
        return 100.0
    if days <= 180:
        return 80.0
    if days <= 365:
        return 60.0
    return 40.0


def _evidence_max(ranked: list[RankedArticle]) -> str:
    """Return the highest evidence level among a set of ranked articles."""
    best = "other"
    best_order = 0
    for r in ranked:
        order = _EVIDENCE_ORDER.get(r.assessment.evidence_level, 0)
        if order > best_order:
            best_order = order
            best = r.assessment.evidence_level
    return best


def _term_in_article(term: str, article) -> bool:
    """Check if a normalized term appears in an article's title/abstract/MeSH/keywords."""
    norm = _normalize_term(term)
    haystacks = [
        article.title,
        article.abstract,
        " ".join(article.mesh_headings),
        " ".join(article.keywords),
    ]
    return any(norm in _normalize_term(h) for h in haystacks if h)


def _term_in_title(term: str, article) -> bool:
    """Check if a normalized term appears in the article title."""
    return _normalize_term(term) in _normalize_term(article.title)


def _term_in_abstract(term: str, article) -> bool:
    """Check if a normalized term appears in the article abstract."""
    return _normalize_term(term) in _normalize_term(article.abstract)


def _candidate_terms_from_articles(
    ranked: list[RankedArticle],
) -> dict[str, dict]:
    """Collect candidate terms from MeSH headings and keywords.

    Returns a dict keyed by normalized term with metadata:
    {term: {"source": ..., "pmids": [...], "ranked": [RankedArticle, ...]}}
    """
    candidates: dict[str, dict] = {}

    for r in ranked:
        article = r.article
        for heading in article.mesh_headings:
            norm = _normalize_term(heading)
            if not norm or norm in _STOPWORDS:
                continue
            entry = candidates.setdefault(
                norm,
                {"source": "mesh", "pmids": [], "ranked": []},
            )
            if article.pmid not in entry["pmids"]:
                entry["pmids"].append(article.pmid)
                entry["ranked"].append(r)

        for keyword in article.keywords:
            norm = _normalize_term(keyword)
            if not norm or norm in _STOPWORDS:
                continue
            entry = candidates.setdefault(
                norm,
                {"source": "keyword", "pmids": [], "ranked": []},
            )
            if article.pmid not in entry["pmids"]:
                entry["pmids"].append(article.pmid)
                entry["ranked"].append(r)

    return candidates


def _score_candidate(
    term: str,
    source: str,
    pmids: list[str],
    ranked: list[RankedArticle],
    topic: str,
    fetched_at: datetime,
    max_df: int,
) -> CandidateTerm:
    """Score a single candidate term and build its reasons."""
    df = len(pmids)
    df_norm = df / max_df if max_df else 0.0

    ev_max = _evidence_max(ranked)
    ev_bonus = _EVIDENCE_BONUS.get(ev_max, 20.0)

    # Recency: days since most recent supporting article.
    most_recent = max(
        (r.article.publication_date or r.article.electronic_publication_date
         for r in ranked if r.article.publication_date or r.article.electronic_publication_date),
        default=None,
    )
    if most_recent is not None:
        recency_days = max(0, (fetched_at.date() - most_recent).days)
    else:
        recency_days = 9999
    rec_bonus = _recency_bonus(recency_days)

    overlap = _direct_topic_overlap(term, topic)

    # Title/abstract boost (support only, capped).
    boost = 0.0
    for r in ranked:
        if _term_in_title(term, r.article):
            boost = max(boost, TITLE_BOOST)
        elif _term_in_abstract(term, r.article):
            boost = max(boost, ABSTRACT_BOOST)
    boost = min(boost, BOOST_CAP)

    score = (
        0.40 * df_norm * 100
        + 0.30 * ev_bonus
        + 0.20 * rec_bonus
        + 0.10 * overlap * 100
        + boost
    )
    score = round(min(score, 100.0), 1)

    reasons = [
        f"document frequency {df}/{max_df} (40%)",
        f"evidence {ev_max} (30%)",
        f"recency {recency_days}d (20%)",
        f"direct topic overlap {overlap:.2f} (10%)",
    ]
    if boost > 0:
        reasons.append(f"title/abstract boost +{boost:.0f} (support only)")

    accepted = df >= MIN_DF and score >= SCORE_ACCEPT_THRESHOLD

    return CandidateTerm(
        term=term,
        source=source,
        document_frequency=df,
        evidence_max=ev_max,
        recency_days=recency_days,
        direct_topic_overlap=round(overlap, 2),
        supporting_articles=tuple(pmids),
        score=score,
        reasons=tuple(reasons),
        accepted=accepted,
    )


def build_topic_profile(
    topic: str,
    ranked: list[RankedArticle],
    fetched_at: datetime,
) -> TopicProfile:
    """Build a topic profile from ranked articles.

    The original free-text ``topic`` is always the primary query and is never
    modified. Discovered terms are saved/displayed but not used to alter
    retrieval in v1.
    """
    candidates = _candidate_terms_from_articles(ranked)
    if not candidates:
        return TopicProfile(
            topic=topic,
            query=topic,
            run_at=fetched_at,
            accepted_terms=(),
            rejected_terms=(),
        )

    max_df = max(len(entry["pmids"]) for entry in candidates.values())

    scored: list[CandidateTerm] = []
    for norm, entry in candidates.items():
        scored.append(
            _score_candidate(
                term=norm,
                source=entry["source"],
                pmids=entry["pmids"],
                ranked=entry["ranked"],
                topic=topic,
                fetched_at=fetched_at,
                max_df=max_df,
            )
        )

    # Deduplicate near-duplicates (case/accent-insensitive already handled by norm).
    # Keep the highest-scoring candidate for each normalized term.
    seen: set[str] = set()
    unique: list[CandidateTerm] = []
    for c in sorted(scored, key=lambda c: -c.score):
        if c.term in seen:
            continue
        seen.add(c.term)
        unique.append(c)

    accepted = tuple(c for c in unique if c.accepted)
    rejected = tuple(c for c in unique if not c.accepted)

    return TopicProfile(
        topic=topic,
        query=topic,
        run_at=fetched_at,
        accepted_terms=accepted,
        rejected_terms=rejected,
    )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

DEFAULT_PROFILE_DIR = Path("data/topic_profiles")


def _slugify(topic: str) -> str:
    """Create a deterministic filesystem-safe slug from a topic string."""
    slug = re.sub(r"[^a-z0-9]+", "_", topic.lower()).strip("_")
    if not slug:
        return "topic"
    if len(slug) > 120:
        digest = hashlib.sha256(topic.encode("utf-8")).hexdigest()[:12]
        slug = f"{slug[:107].rstrip('_')}_{digest}"
    return slug


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


def _profile_to_dict(p: TopicProfile) -> dict:
    return {
        "topic": p.topic,
        "query": p.query,
        "run_at": p.run_at.isoformat(),
        "accepted_terms": [_candidate_to_dict(c) for c in p.accepted_terms],
        "rejected_terms": [_candidate_to_dict(c) for c in p.rejected_terms],
    }


def _dict_to_candidate(d: dict) -> CandidateTerm:
    return CandidateTerm(
        term=d["term"],
        source=d["source"],
        document_frequency=d["document_frequency"],
        evidence_max=d["evidence_max"],
        recency_days=d["recency_days"],
        direct_topic_overlap=d["direct_topic_overlap"],
        supporting_articles=tuple(d["supporting_articles"]),
        score=d["score"],
        reasons=tuple(d["reasons"]),
        accepted=d["accepted"],
    )


def _dict_to_profile(d: dict) -> TopicProfile:
    return TopicProfile(
        topic=d["topic"],
        query=d["query"],
        run_at=datetime.fromisoformat(d["run_at"]),
        accepted_terms=tuple(_dict_to_candidate(c) for c in d["accepted_terms"]),
        rejected_terms=tuple(_dict_to_candidate(c) for c in d["rejected_terms"]),
    )


def save_topic_profile(
    profile: TopicProfile,
    output_dir: Path = DEFAULT_PROFILE_DIR,
) -> Path:
    """Write the topic profile to a JSON file and return its path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{_slugify(profile.topic)}.json"
    path.write_text(
        json.dumps(_profile_to_dict(profile), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def load_topic_profile(path: Path) -> TopicProfile | None:
    """Load a topic profile from a JSON file, or ``None`` if missing/invalid."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return _dict_to_profile(data)
    except (json.JSONDecodeError, KeyError, ValueError):
        return None


def profile_path_for_topic(topic: str, output_dir: Path = DEFAULT_PROFILE_DIR) -> Path:
    """Return the expected profile path for a topic."""
    return output_dir / f"{_slugify(topic)}.json"


def merge_topic_profiles(
    existing: TopicProfile | None,
    new: TopicProfile,
) -> TopicProfile:
    """Merge a new profile into an existing one without duplicating terms.

    Accepted terms accumulate across runs (dedup by normalized term). Terms
    that no longer meet thresholds are moved to rejected but never removed.
    """
    if existing is None:
        return new

    merged_accepted: dict[str, CandidateTerm] = {}
    merged_rejected: dict[str, CandidateTerm] = {}

    for c in existing.accepted_terms:
        merged_accepted[c.term] = c
    for c in existing.rejected_terms:
        merged_rejected[c.term] = c

    for c in new.accepted_terms:
        if c.term in merged_accepted:
            # Keep the higher-scoring version.
            if c.score > merged_accepted[c.term].score:
                merged_accepted[c.term] = c
        elif c.term in merged_rejected:
            # Upgrade from rejected to accepted.
            del merged_rejected[c.term]
            merged_accepted[c.term] = c
        else:
            merged_accepted[c.term] = c

    for c in new.rejected_terms:
        if c.term not in merged_accepted and c.term not in merged_rejected:
            merged_rejected[c.term] = c

    return TopicProfile(
        topic=new.topic,
        query=new.query,
        run_at=new.run_at,
        accepted_terms=tuple(sorted(merged_accepted.values(), key=lambda c: -c.score)),
        rejected_terms=tuple(sorted(merged_rejected.values(), key=lambda c: -c.score)),
    )