"""Tests for the rule-based evidence classification and ranking layer."""

from datetime import date, datetime

from app.models.article import Article
from app.services.evidence import (
    assess_article,
    classify_evidence_level,
    rank_articles,
)

FIXED_DT = datetime(2026, 8, 10, 9, 30, 0)


def _article(
    pmid="1",
    title="Test article",
    abstract="",
    publication_date=None,
    publication_date_raw="",
    electronic_publication_date=None,
    is_epub_ahead_of_print=False,
    publication_types=("Journal Article",),
) -> Article:
    return Article(
        pmid=pmid,
        title=title,
        abstract=abstract,
        publication_date=publication_date,
        publication_date_raw=publication_date_raw,
        electronic_publication_date=electronic_publication_date,
        is_epub_ahead_of_print=is_epub_ahead_of_print,
        publication_types=publication_types,
    )


def test_classify_guideline():
    level, label = classify_evidence_level(("Journal Article", "Practice Guideline"))
    assert level == "guideline"
    assert label == "Guideline"


def test_classify_systematic_review():
    level, label = classify_evidence_level(("Journal Article", "Systematic Review"))
    assert level == "systematic_review"
    assert "Systematic Review" in label


def test_classify_meta_analysis():
    level, _ = classify_evidence_level(("Journal Article", "Meta-Analysis"))
    assert level == "systematic_review"


def test_classify_randomized_trial():
    level, label = classify_evidence_level(("Journal Article", "Randomized Controlled Trial"))
    assert level == "randomized_trial"
    assert "Randomized" in label


def test_classify_clinical_trial():
    level, _ = classify_evidence_level(("Journal Article", "Clinical Trial"))
    assert level == "randomized_trial"


def test_classify_observational():
    level, _ = classify_evidence_level(("Journal Article", "Observational Study"))
    assert level == "observational"


def test_classify_cohort():
    level, _ = classify_evidence_level(("Journal Article", "Cohort Studies"))
    assert level == "observational"


def test_classify_narrative_review():
    level, _ = classify_evidence_level(("Journal Article", "Review"))
    assert level == "narrative_review"


def test_classify_editorial():
    level, _ = classify_evidence_level(("Journal Article", "Editorial"))
    assert level == "narrative_review"


def test_classify_other():
    level, _ = classify_evidence_level(("Journal Article",))
    assert level == "other"


def test_classify_priority_order():
    # Both "Review" and "Systematic Review" present -> systematic_review wins.
    level, _ = classify_evidence_level(("Journal Article", "Review", "Systematic Review"))
    assert level == "systematic_review"


def test_no_abstract_sets_status_not_available():
    a = _article(abstract="")
    assessment = assess_article(a, FIXED_DT)
    assert assessment.has_abstract is False
    assert assessment.abstract_status == "not_available"
    assert "No abstract available in PubMed" in assessment.limitations


def test_abstract_available():
    a = _article(abstract="Some abstract text here.")
    assessment = assess_article(a, FIXED_DT)
    assert assessment.has_abstract is True
    assert assessment.abstract_status == "available"


def test_future_issue_dated_flag():
    a = _article(publication_date=date(2026, 12, 1), publication_date_raw="2026 Dec")
    assessment = assess_article(a, FIXED_DT)
    assert assessment.is_future_issue_dated is True
    assert assessment.section == "exploratory_evidence"
    assert any("future" in lim.lower() for lim in assessment.limitations)


def test_electronic_only_not_future_dated():
    a = _article(
        publication_date=None,
        publication_date_raw="",
        electronic_publication_date=date(2026, 6, 15),
        is_epub_ahead_of_print=True,
    )
    assessment = assess_article(a, FIXED_DT)
    assert assessment.is_future_issue_dated is False
    assert assessment.is_electronic_only is True
    assert "Available electronically ahead of print" in assessment.limitations


def test_scores_within_range():
    a = _article(abstract="Some abstract", publication_types=("Journal Article", "Systematic Review"))
    assessment = assess_article(a, FIXED_DT)
    assert 0 <= assessment.evidence_score <= 100
    assert 0 <= assessment.relevance_score <= 100
    assert 0 <= assessment.overall_score <= 100


def test_section_assignment_thresholds():
    # High score -> key_evidence.
    a = _article(
        title="GLP-1 receptor agonists for type 2 diabetes",
        abstract="GLP-1 receptor agonists improve outcomes in type 2 diabetes.",
        publication_types=("Journal Article", "Systematic Review"),
    )
    assessment = assess_article(a, FIXED_DT, topic="GLP-1 receptor agonists")
    assert assessment.section == "key_evidence"

    # Low score -> exploratory.
    a2 = _article(
        title="Unrelated topic",
        abstract="",
        publication_types=("Journal Article",),
    )
    assessment2 = assess_article(a2, FIXED_DT, topic="GLP-1 receptor agonists")
    assert assessment2.section == "exploratory_evidence"


def test_rank_articles_sorts_by_section_then_score():
    articles = [
        _article(pmid="1", title="Low quality", publication_types=("Journal Article",)),
        _article(
            pmid="2",
            title="GLP-1 receptor agonists for type 2 diabetes",
            abstract="GLP-1 receptor agonists improve outcomes in type 2 diabetes.",
            publication_types=("Journal Article", "Systematic Review"),
        ),
        _article(
            pmid="3",
            title="Medium quality",
            abstract="Some abstract.",
            publication_types=("Journal Article", "Observational Study"),
        ),
    ]
    ranked = rank_articles(articles, FIXED_DT, topic="GLP-1 receptor agonists")
    sections = [r.assessment.section for r in ranked]
    # Key evidence first, then important/exploratory.
    assert sections[0] == "key_evidence"
    assert sections[-1] == "exploratory_evidence"


def test_empty_articles_list():
    assert rank_articles([], FIXED_DT, topic="test") == []