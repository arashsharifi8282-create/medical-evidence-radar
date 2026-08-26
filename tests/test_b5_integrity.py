"""Offline Phase B5 publication-integrity policy and integration tests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from app.models.article import Article
from app.models.relevance import AssessedCandidate, ClinicalRelevanceAssessment
from app.services.integrity import assess_publication_integrity
from app.services.normalizer import normalize_article, parse_pubmed_articles
from app.services.persistence import build_html_report, build_markdown_report, build_snapshot
from app.services.relevance import rank_and_select_candidates


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "b5_publication_integrity"
FIXED_DT = datetime(2026, 8, 27, 9, 0, 0)


def _fixture_articles() -> list[Article]:
    xml = (FIXTURE_DIR / "records.xml").read_text(encoding="utf-8")
    return [normalize_article(item) for item in parse_pubmed_articles(xml)]


def _relevance(pmid: str, relevance_class: str = "direct") -> ClinicalRelevanceAssessment:
    return ClinicalRelevanceAssessment(
        pmid=pmid,
        relevance_class=relevance_class,
        relevance_score=90,
        intervention_signals=(),
        condition_signals=(),
        decision=f"included_{relevance_class}",
        reason="Controlled relevance decision.",
        assessed_at=FIXED_DT,
        query_intents=("efficacy",),
        article_intents=("efficacy",),
        article_focus="target_intervention_primary",
    )


def test_fixture_membership_and_checksums_are_controlled():
    manifest = json.loads((FIXTURE_DIR / "manifest.json").read_text(encoding="utf-8"))
    expected = json.loads((FIXTURE_DIR / "expected.json").read_text(encoding="utf-8"))
    articles = _fixture_articles()
    assert [item.pmid for item in articles] == manifest["record_pmids"]
    assert len({item.pmid for item in articles}) == manifest["record_count"]
    assert [item["pmid"] for item in expected["records"]] == manifest["record_pmids"]
    for name, checksum in manifest["checksums"].items():
        assert hashlib.sha256((FIXTURE_DIR / name).read_bytes()).hexdigest() == checksum


def test_comments_corrections_are_normalized_with_structured_provenance():
    articles = _fixture_articles()
    original = articles[0]
    assert original.publication_types == ("Journal Article", "Retracted Publication")
    relation = original.integrity_relations[0]
    assert relation.raw_ref_type == "RetractionIn"
    assert relation.normalized_relation == "retraction_in"
    assert relation.related_pmid == "99000002"
    assert relation.related_doi is None
    assert relation.source_text == "Retraction notice <unsafe>."
    assert relation.source_field == "CommentsCorrections"
    assert relation.rule_version == "1.0"


def test_incomplete_unknown_and_duplicate_relations_are_auditable_and_deterministic():
    article = _fixture_articles()[-1]
    assert len(article.integrity_relations) == 3
    assert [item.raw_ref_type for item in article.integrity_relations] == [
        "ErratumIn", "RetractionIn", "UnknownFutureRelation"
    ]
    unknown = article.integrity_relations[-1]
    assert unknown.normalized_relation == "unknown"
    assert unknown.related_pmid is None and unknown.related_doi is None


def test_fixture_taxonomy_matches_expected_labels():
    expected = json.loads((FIXTURE_DIR / "expected.json").read_text(encoding="utf-8"))
    actual = {item.pmid: assess_publication_integrity(item) for item in _fixture_articles()}
    for label in expected["records"]:
        assessment = actual[label["pmid"]]
        assert assessment.status == label["status"]
        assert assessment.record_role == label["record_role"]
        assert assessment.report_eligible is label["report_eligible"]
        assert assessment.needs_review is label["needs_review"]


def test_precedence_conflicts_and_permutation_invariance():
    article = _fixture_articles()[-1]
    forward = assess_publication_integrity(article)
    reverse = assess_publication_integrity(replace(article, integrity_relations=tuple(reversed(article.integrity_relations))))
    assert forward == reverse
    assert forward.status == "retracted"
    assert forward.needs_review is True
    assert "CONFLICTING_STRUCTURED_SIGNALS" in forward.reason_codes
    assert "UNKNOWN_REF_TYPE" in forward.reason_codes


def test_free_text_integrity_words_are_not_signals():
    assessment = assess_publication_integrity(_fixture_articles()[7])
    assert assessment.status == "no_signal"
    assert assessment.report_eligible is True
    assert assessment.reason == "No publication-integrity warning was found in the retained PubMed metadata."


def test_official_non_integrity_comments_corrections_do_not_create_warning():
    article = replace(
        _fixture_articles()[7],
        integrity_relations=(
            replace(
                _fixture_articles()[0].integrity_relations[0],
                normalized_relation="comment_in",
                raw_ref_type="CommentIn",
            ),
        ),
    )
    assessment = assess_publication_integrity(article)
    assert assessment.status == "no_signal"
    assert assessment.report_eligible is True


def test_retracted_direct_article_keeps_relevance_and_backfills_report_limit():
    articles = _fixture_articles()
    source = [articles[0], articles[7], Article(pmid="99000010", title="Eligible result", abstract="Randomized trial efficacy results.", publication_types=("Journal Article",))]
    candidates = [AssessedCandidate(item, _relevance(item.pmid), assess_publication_integrity(item)) for item in source]
    selected, audited, all_ranked = rank_and_select_candidates(candidates, FIXED_DT, "generic topic", 2)
    assert [item.article.pmid for item in selected] == ["99000010", "99000008"]
    retracted = next(item for item in audited if item.article.pmid == "99000001")
    assert retracted.relevance.relevance_class == "direct"
    assert retracted.relevance.decision == "included_direct"
    assert retracted.integrity.final_decision == "excluded_integrity"
    assert all(item.article.pmid != "99000001" for item in all_ranked)


def test_corrected_primary_remains_eligible_but_notices_and_eoc_do_not_rank():
    articles = _fixture_articles()
    candidates = [AssessedCandidate(item, _relevance(item.pmid), assess_publication_integrity(item)) for item in articles]
    _, audited, all_ranked = rank_and_select_candidates(candidates, FIXED_DT, "generic topic", 9)
    ranked_pmids = {item.article.pmid for item in all_ranked}
    assert "99000005" in ranked_pmids and "99000007" in ranked_pmids
    assert {"99000001", "99000002", "99000003", "99000004", "99000006", "99000009"}.isdisjoint(ranked_pmids)
    assert all(item.integrity is not None for item in audited)


def test_json_and_renderers_preserve_integrity_without_duplicate_representation():
    articles = _fixture_articles()
    candidates = [AssessedCandidate(item, _relevance(item.pmid), assess_publication_integrity(item)) for item in articles]
    selected, audited, _ = rank_and_select_candidates(candidates, FIXED_DT, "generic topic", 3)
    snapshot = build_snapshot(topic="generic topic", query="generic topic", fetched_at=FIXED_DT, ranked=selected, candidates=tuple(audited))
    markdown = build_markdown_report(topic="generic topic", fetched_at=FIXED_DT, ranked=selected, candidates=tuple(audited))
    html = build_html_report(topic="generic topic", fetched_at=FIXED_DT, ranked=selected, candidates=tuple(audited))

    by_pmid = {item["pmid"]: item for item in snapshot["articles"]}
    assert snapshot["schema_version"] == "b5"
    assert by_pmid["99000001"]["publication_integrity"]["status"] == "retracted"
    assert by_pmid["99000001"]["assessment"] is None
    assert by_pmid["99000001"]["report_placement"]["section"] == "publication_integrity_warnings"
    assert by_pmid["99000005"]["publication_integrity"]["report_eligible"] is True
    assert markdown.count("### Retracted original") == 1
    assert html.count('data-pmid="99000001"') == 1
    assert "Publication integrity warnings" in markdown
    assert "Publication integrity warnings" in html
    assert "Retraction notice &lt;unsafe&gt;." in html
    assert "Retraction notice <unsafe>." not in html
    assert set(snapshot["represented_article_pmids"]) == set(snapshot["primary_article_pmids"] + snapshot["collapsed_article_pmids"] + snapshot["integrity_warning_pmids"])


def test_no_selected_disappearance_and_renderer_visibility_agreement():
    articles = _fixture_articles()
    candidates = [AssessedCandidate(item, _relevance(item.pmid), assess_publication_integrity(item)) for item in articles]
    selected, audited, _ = rank_and_select_candidates(candidates, FIXED_DT, "generic topic", 3)
    snapshot = build_snapshot(topic="generic topic", query="generic topic", fetched_at=FIXED_DT, ranked=selected, candidates=tuple(audited))
    md = build_markdown_report(topic="generic topic", fetched_at=FIXED_DT, ranked=selected, candidates=tuple(audited))
    html = build_html_report(topic="generic topic", fetched_at=FIXED_DT, ranked=selected, candidates=tuple(audited))
    represented = snapshot["represented_article_pmids"]
    assert len(represented) == len(set(represented))
    title_by_pmid = {item.pmid: item.title for item in articles}
    for pmid in represented:
        assert md.count(title_by_pmid[pmid]) >= 1
        assert html.count(f'data-pmid="{pmid}"') == 1


def test_production_code_has_no_fixture_specific_constants():
    production = "\n".join(path.read_text(encoding="utf-8") for path in Path("app").rglob("*.py"))
    assert "9900000" not in production
    assert "b5_publication_integrity" not in production
