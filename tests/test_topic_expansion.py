"""Tests for automatic topic-term discovery from MeSH headings and keywords."""

from datetime import date, datetime
from pathlib import Path

from app.models.article import Article
from app.models.assessment import RankedArticle
from app.services.evidence import assess_article
from app.services.topic_expansion import (
    MIN_DF,
    SCORE_ACCEPT_THRESHOLD,
    build_topic_profile,
    merge_topic_profiles,
)

FIXED_DT = datetime(2026, 8, 10, 9, 30, 0)


def _ranked(
    pmid: str,
    title: str = "",
    abstract: str = "",
    mesh: tuple[str, ...] = (),
    keywords: tuple[str, ...] = (),
    publication_types: tuple[str, ...] = ("Journal Article",),
    publication_date: date | None = None,
) -> RankedArticle:
    article = Article(
        pmid=pmid,
        title=title,
        abstract=abstract,
        publication_date=publication_date,
        publication_types=publication_types,
        mesh_headings=mesh,
        keywords=keywords,
    )
    return RankedArticle(article=article, assessment=assess_article(article, FIXED_DT))


def test_mesh_headings_are_candidates():
    ranked = [
        _ranked("1", mesh=("Diabetes Mellitus, Type 2", "Obesity")),
        _ranked("2", mesh=("Diabetes Mellitus, Type 2", "Heart Failure")),
    ]
    profile = build_topic_profile("GLP-1 receptor agonists", ranked, FIXED_DT)
    terms = {c.term for c in profile.accepted_terms + profile.rejected_terms}
    assert "diabetes mellitus, type 2" in terms
    assert "obesity" in terms
    assert "heart failure" in terms


def test_author_keywords_are_candidates():
    ranked = [
        _ranked("1", keywords=("semaglutide", "weight loss")),
        _ranked("2", keywords=("semaglutide", "obesity")),
    ]
    profile = build_topic_profile("GLP-1 receptor agonists", ranked, FIXED_DT)
    terms = {c.term for c in profile.accepted_terms + profile.rejected_terms}
    assert "semaglutide" in terms
    assert "weight loss" in terms


def test_title_abstract_phrases_are_not_independent_candidates():
    # A term that appears only in title/abstract (not MeSH/keywords) must NOT be a candidate.
    ranked = [
        _ranked("1", title="Novel biomarker XYZ123 in diabetes", abstract="XYZ123 is elevated."),
        _ranked("2", title="Another study of XYZ123", abstract="XYZ123 correlates with outcomes."),
    ]
    profile = build_topic_profile("GLP-1 receptor agonists", ranked, FIXED_DT)
    terms = {c.term for c in profile.accepted_terms + profile.rejected_terms}
    assert "xyz123" not in terms


def test_min_df_enforced():
    # A term in only 1 article must be rejected (below MIN_DF=2).
    ranked = [
        _ranked("1", mesh=("Rare Term",)),
        _ranked("2", mesh=("Common Term",)),
    ]
    profile = build_topic_profile("test topic", ranked, FIXED_DT)
    rare = [c for c in profile.accepted_terms + profile.rejected_terms if c.term == "rare term"]
    assert rare
    assert rare[0].document_frequency == 1
    assert rare[0].accepted is False


def test_zero_overlap_term_can_be_accepted():
    # "semaglutide" has zero lexical overlap with "GLP-1 receptor agonists"
    # but is supported by keywords across 2 articles with strong evidence.
    ranked = [
        _ranked(
            "1",
            title="Semaglutide in obesity",
            abstract="Semaglutide improved weight.",
            keywords=("semaglutide",),
            publication_types=("Journal Article", "Randomized Controlled Trial"),
            publication_date=date(2026, 7, 1),
        ),
        _ranked(
            "2",
            title="Semaglutide and heart failure",
            abstract="Semaglutide improved symptoms.",
            keywords=("semaglutide",),
            publication_types=("Journal Article", "Randomized Controlled Trial"),
            publication_date=date(2026, 7, 15),
        ),
    ]
    profile = build_topic_profile("GLP-1 receptor agonists", ranked, FIXED_DT)
    sema = [c for c in profile.accepted_terms if c.term == "semaglutide"]
    assert sema, "semaglutide should be accepted despite zero lexical overlap"
    assert sema[0].direct_topic_overlap == 0.0
    assert sema[0].accepted is True


def test_stopwords_excluded():
    ranked = [
        _ranked("1", mesh=("Humans", "Female", "Diabetes Mellitus, Type 2")),
        _ranked("2", mesh=("Humans", "Male", "Diabetes Mellitus, Type 2")),
    ]
    profile = build_topic_profile("test", ranked, FIXED_DT)
    terms = {c.term for c in profile.accepted_terms + profile.rejected_terms}
    assert "humans" not in terms
    assert "female" not in terms
    assert "male" not in terms
    assert "diabetes mellitus, type 2" in terms


def test_query_never_modified():
    ranked = [
        _ranked("1", mesh=("Diabetes Mellitus, Type 2",)),
        _ranked("2", mesh=("Diabetes Mellitus, Type 2",)),
    ]
    profile = build_topic_profile("GLP-1 receptor agonists for weight loss", ranked, FIXED_DT)
    assert profile.query == "GLP-1 receptor agonists for weight loss"
    assert profile.topic == "GLP-1 receptor agonists for weight loss"


def test_accepted_terms_have_reasons():
    ranked = [
        _ranked(
            "1",
            keywords=("semaglutide",),
            publication_types=("Journal Article", "Randomized Controlled Trial"),
            publication_date=date(2026, 7, 1),
        ),
        _ranked(
            "2",
            keywords=("semaglutide",),
            publication_types=("Journal Article", "Randomized Controlled Trial"),
            publication_date=date(2026, 7, 15),
        ),
    ]
    profile = build_topic_profile("GLP-1 receptor agonists", ranked, FIXED_DT)
    sema = [c for c in profile.accepted_terms if c.term == "semaglutide"]
    assert sema
    assert len(sema[0].reasons) >= 4
    assert any("document frequency" in r for r in sema[0].reasons)
    assert any("evidence" in r for r in sema[0].reasons)
    assert any("recency" in r for r in sema[0].reasons)
    assert any("topic overlap" in r for r in sema[0].reasons)


def test_empty_articles_returns_empty_profile():
    profile = build_topic_profile("test topic", [], FIXED_DT)
    assert profile.accepted_terms == ()
    assert profile.rejected_terms == ()
    assert profile.query == "test topic"


def test_merge_profiles_no_duplicates():
    ranked1 = [
        _ranked("1", keywords=("semaglutide",), publication_types=("Journal Article", "Randomized Controlled Trial")),
        _ranked("2", keywords=("semaglutide",), publication_types=("Journal Article", "Randomized Controlled Trial")),
    ]
    profile1 = build_topic_profile("GLP-1 receptor agonists", ranked1, FIXED_DT)

    ranked2 = [
        _ranked("3", keywords=("semaglutide", "tirzepatide"), publication_types=("Journal Article", "Randomized Controlled Trial")),
        _ranked("4", keywords=("semaglutide", "tirzepatide"), publication_types=("Journal Article", "Randomized Controlled Trial")),
    ]
    profile2 = build_topic_profile("GLP-1 receptor agonists", ranked2, FIXED_DT)

    merged = merge_topic_profiles(profile1, profile2)
    sema_terms = [c for c in merged.accepted_terms if c.term == "semaglutide"]
    assert len(sema_terms) == 1  # no duplicate
    tirz_terms = [c for c in merged.accepted_terms if c.term == "tirzepatide"]
    assert len(tirz_terms) == 1  # new term added