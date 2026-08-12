"""Tests for topic profile JSON persistence and merging."""

from datetime import date, datetime
from pathlib import Path

from app.models.article import Article
from app.models.assessment import RankedArticle
from app.services.evidence import assess_article
from app.services.topic_expansion import (
    build_topic_profile,
    load_topic_profile,
    merge_topic_profiles,
    profile_path_for_topic,
    save_topic_profile,
)

FIXED_DT = datetime(2026, 8, 10, 9, 30, 0)


def _ranked(
    pmid: str,
    keywords: tuple[str, ...] = (),
    publication_types: tuple[str, ...] = ("Journal Article",),
) -> RankedArticle:
    article = Article(
        pmid=pmid,
        title="Test",
        abstract="",
        publication_types=publication_types,
        keywords=keywords,
    )
    return RankedArticle(article=article, assessment=assess_article(article, FIXED_DT))


def test_profile_roundtrip(tmp_path: Path):
    ranked = [
        _ranked("1", keywords=("semaglutide",), publication_types=("Journal Article", "Randomized Controlled Trial")),
        _ranked("2", keywords=("semaglutide",), publication_types=("Journal Article", "Randomized Controlled Trial")),
    ]
    profile = build_topic_profile("GLP-1 receptor agonists", ranked, FIXED_DT)

    path = save_topic_profile(profile, output_dir=tmp_path)
    assert path.exists()

    loaded = load_topic_profile(path)
    assert loaded is not None
    assert loaded.topic == profile.topic
    assert loaded.query == profile.query
    assert len(loaded.accepted_terms) == len(profile.accepted_terms)
    assert len(loaded.rejected_terms) == len(profile.rejected_terms)
    if profile.accepted_terms:
        assert loaded.accepted_terms[0].term == profile.accepted_terms[0].term
        assert loaded.accepted_terms[0].score == profile.accepted_terms[0].score


def test_profile_path_bounds_long_topic_filename(tmp_path):
    topic = "MASLD mechanisms " + "resmetirom semaglutide FGF21 pan PPAR " * 20
    path = profile_path_for_topic(topic, output_dir=tmp_path)

    assert len(path.stem) <= 120
    assert len(path.stem.rsplit("_", 1)[-1]) == 12


def test_load_missing_returns_none(tmp_path: Path):
    assert load_topic_profile(tmp_path / "missing.json") is None


def test_profile_path_for_topic(tmp_path: Path):
    path = profile_path_for_topic("GLP-1 receptor agonists", output_dir=tmp_path)
    assert path.parent == tmp_path
    assert path.name == "glp_1_receptor_agonists.json"


def test_merge_incremental_no_duplicates():
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
    sema = [c for c in merged.accepted_terms if c.term == "semaglutide"]
    assert len(sema) == 1
    tirz = [c for c in merged.accepted_terms if c.term == "tirzepatide"]
    assert len(tirz) == 1


def test_merge_none_existing_returns_new():
    ranked = [
        _ranked("1", keywords=("semaglutide",), publication_types=("Journal Article", "Randomized Controlled Trial")),
        _ranked("2", keywords=("semaglutide",), publication_types=("Journal Article", "Randomized Controlled Trial")),
    ]
    profile = build_topic_profile("GLP-1 receptor agonists", ranked, FIXED_DT)
    merged = merge_topic_profiles(None, profile)
    assert merged == profile