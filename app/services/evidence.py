"""Rule-based evidence classification, scoring, and triage for articles.

This module is pure: it takes normalized :class:`Article` records plus a fetch
timestamp and returns :class:`RankedArticle` records with transparent,
explainable assessments. No network calls are made here.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from app.models.article import Article
from app.models.assessment import EvidenceAssessment, RankedArticle

# ---------------------------------------------------------------------------
# Evidence-level classification
# ---------------------------------------------------------------------------

# Priority-ordered: first matching level wins.
_EVIDENCE_RULES: list[tuple[str, str, tuple[str, ...]]] = [
    ("guideline", "Guideline", ("guideline",)),
    (
        "systematic_review",
        "Systematic Review / Meta-Analysis",
        ("systematic review", "meta-analysis"),
    ),
    (
        "randomized_trial",
        "Randomized Controlled Trial",
        (
            "randomized controlled trial",
            "controlled clinical trial",
            "pragmatic clinical trial",
            "clinical trial",
        ),
    ),
    (
        "observational",
        "Observational Study",
        (
            "observational study",
            "cohort studies",
            "case-control studies",
            "cross-sectional studies",
            "longitudinal studies",
            "retrospective",
            "prospective",
        ),
    ),
    (
        "narrative_review",
        "Narrative Review / Expert Opinion",
        ("review", "comment", "editorial", "letter", "consensus", "expert opinion"),
    ),
]

_EVIDENCE_BASE_SCORES = {
    "guideline": 95,
    "systematic_review": 90,
    "randomized_trial": 85,
    "observational": 65,
    "narrative_review": 45,
    "other": 30,
}

_EVIDENCE_LABELS = {
    "guideline": "Guideline",
    "systematic_review": "Systematic Review / Meta-Analysis",
    "randomized_trial": "Randomized Controlled Trial",
    "observational": "Observational Study",
    "narrative_review": "Narrative Review / Expert Opinion",
    "other": "Other",
}

# ---------------------------------------------------------------------------
# Topic relevance (lexical, low-weight)
# ---------------------------------------------------------------------------

_STOPWORDS = {
    "a", "an", "the", "and", "or", "for", "in", "of", "on", "with", "to",
    "from", "by", "at", "as", "is", "are", "was", "were", "be", "been",
    "study", "studies", "patients", "patient", "results", "result", "treatment",
    "effect", "effects", "analysis", "data", "methods", "method", "conclusion",
    "conclusions", "background", "outcome", "outcomes", "trial", "trials",
    "group", "groups", "found", "compared", "using", "use", "used", "may",
    "can", "could", "should", "among", "between", "during", "after", "before",
    "over", "under", "within", "without", "based", "related", "associated",
    "significant", "significantly", "improved", "improvement", "reduction",
    "increase", "decrease", "risk", "rate", "rates", "level", "levels",
    "score", "scores", "total", "overall", "mean", "median", "range",
    "versus", "vs", "including", "included", "excluded", "performed",
    "conducted", "assessed", "evaluated", "measured", "observed", "reported",
    "showed", "shown", "demonstrated", "suggest", "suggests", "suggested",
    "potential", "possible", "likely", "however", "therefore", "thus",
    "additionally", "furthermore", "moreover", "although", "because", "while",
    "when", "where", "which", "who", "whom", "whose", "this", "that", "these",
    "those", "there", "their", "they", "them", "its", "it", "we", "our",
    "you", "your", "i", "me", "my", "he", "she", "his", "her", "him",
}


def _tokenize(text: str) -> set[str]:
    """Lowercase, strip punctuation, and return a set of non-stopword tokens."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if w and w not in _STOPWORDS}


def _relevance_score(article: Article, topic: str) -> int:
    """Compute a transparent relevance score (0-100) for an article."""
    terms = _tokenize(topic)
    if not terms:
        return 50

    title_tokens = _tokenize(article.title)
    abstract_tokens = _tokenize(article.abstract)

    title_matches = len(terms & title_tokens)
    abstract_matches = len(terms & abstract_tokens)

    score = 50
    if title_matches:
        score += 10
    if abstract_matches and not title_matches:
        score += 5
    if title_matches >= 2:
        score += 10
    return min(score, 100)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def classify_evidence_level(publication_types: tuple[str, ...]) -> tuple[str, str]:
    """Classify an article's evidence level from its publication types.

    Returns ``(level_key, level_label)``. Priority-ordered first match wins.
    """
    for level, label, patterns in _EVIDENCE_RULES:
        for pt in publication_types:
            pt_lower = pt.lower()
            if any(pattern in pt_lower for pattern in patterns):
                return level, label
    return "other", _EVIDENCE_LABELS["other"]


# ---------------------------------------------------------------------------
# Assessment
# ---------------------------------------------------------------------------


def assess_article(
    article: Article,
    fetched_at: datetime,
    topic: str = "",
) -> EvidenceAssessment:
    """Build a transparent evidence assessment for a single article."""
    level, label = classify_evidence_level(article.publication_types)

    # Future-date handling: distinguish journal-issue date from electronic date.
    fetched_date = fetched_at.date()
    is_future_issue_dated = (
        article.publication_date is not None
        and article.publication_date > fetched_date
    )
    is_electronic_only = article.is_epub_ahead_of_print

    has_abstract = bool(article.abstract)
    abstract_status = "available" if has_abstract else "not_available"

    # Evidence score.
    evidence_score = _EVIDENCE_BASE_SCORES[level]
    if has_abstract:
        evidence_score += 5
    if is_future_issue_dated:
        evidence_score -= 20
    evidence_score = max(0, min(100, evidence_score))

    # Relevance score.
    relevance_score = _relevance_score(article, topic)

    # Overall score.
    overall_score = round(0.6 * evidence_score + 0.4 * relevance_score)

    # Reasons (why included).
    reasons: list[str] = []
    if level in ("guideline", "systematic_review", "randomized_trial"):
        reasons.append(f"High-quality evidence level: {label}")
    if relevance_score >= 60:
        reasons.append("Matches topic terms in title or abstract")
    if has_abstract:
        reasons.append("Abstract available for verification")
    if not reasons:
        reasons.append("Retrieved by the topic query")

    # Limitations.
    limitations: list[str] = []
    if not has_abstract:
        limitations.append("No abstract available in PubMed")
    if is_future_issue_dated:
        limitations.append(
            "Journal issue date is in the future relative to fetch date — "
            "scheduled issue, not yet published"
        )
    if is_electronic_only:
        limitations.append("Available electronically ahead of print")
    if level == "observational":
        limitations.append("Lower evidence hierarchy (observational study)")
    if level == "narrative_review":
        limitations.append("Not a primary study (review/comment/editorial)")
    if level == "other":
        limitations.append("Evidence level could not be determined from publication types")

    # Section assignment.
    section = _assign_section(overall_score, is_future_issue_dated)

    return EvidenceAssessment(
        evidence_level=level,
        evidence_level_label=label,
        relevance_score=relevance_score,
        evidence_score=evidence_score,
        overall_score=overall_score,
        is_future_issue_dated=is_future_issue_dated,
        is_electronic_only=is_electronic_only,
        has_abstract=has_abstract,
        abstract_status=abstract_status,
        reasons=tuple(reasons),
        limitations=tuple(limitations),
        section=section,
    )


def _assign_section(overall_score: int, is_future_issue_dated: bool) -> str:
    """Assign a report section based on overall score and future-date flag."""
    if is_future_issue_dated:
        return "exploratory_evidence"
    if overall_score >= 75:
        return "key_evidence"
    if overall_score >= 55:
        return "important_updates"
    return "exploratory_evidence"


def rank_articles(
    articles: list[Article],
    fetched_at: datetime,
    topic: str = "",
) -> list[RankedArticle]:
    """Rank a list of articles, returning them sorted by section then score."""
    ranked = [
        RankedArticle(article=a, assessment=assess_article(a, fetched_at, topic))
        for a in articles
    ]

    section_order = {"key_evidence": 0, "important_updates": 1, "exploratory_evidence": 2}
    ranked.sort(
        key=lambda r: (
            section_order.get(r.assessment.section, 3),
            -r.assessment.overall_score,
            -(r.article.publication_date or date.min).toordinal(),
        )
    )
    return ranked