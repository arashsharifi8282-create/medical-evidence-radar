"""Offline Phase B1 concept identification and safety tests."""

from datetime import datetime
from pathlib import Path

from app.models.topic_profile import CandidateTerm, TopicProfile
from app.services.concept_normalization import ARTICLE_MENTIONS_CONCEPT, normalize_medical_concepts
from app.services.evidence import rank_articles
from app.services.normalizer import normalize_article, parse_pubmed_articles
from app.services.persistence import build_html_report, build_markdown_report, build_snapshot
from app.sources.rxnorm.client import RxNormMatch

FIXTURES = Path(__file__).parent / "fixtures"
XML = (FIXTURES / "efetch_sample.xml").read_text(encoding="utf-8")
NOW = datetime(2026, 8, 10, 9, 30)


class StubRxNormClient:
    def __init__(self, matches=(), error=None):
        self.matches = matches
        self.error = error
        self.terms = []

    def lookup(self, term):
        self.terms.append(term)
        if self.error:
            raise self.error
        return self.matches


def _ranked():
    articles = [normalize_article(item) for item in parse_pubmed_articles(XML)]
    return rank_articles(articles, NOW, "GLP-1-based therapies")


def _profile(term="obesity", source="mesh", pmids=("38521990", "38521950")):
    candidate = CandidateTerm(
        term=term,
        source=source,
        document_frequency=len(pmids),
        evidence_max="randomized_trial",
        recency_days=1,
        direct_topic_overlap=0.0,
        supporting_articles=pmids,
        score=80.0,
        reasons=("fixture",),
        accepted=True,
    )
    return TopicProfile("topic", "topic", NOW, (candidate,), ())


def test_mesh_ui_major_topic_and_supporting_pmid_are_retained():
    article = _ranked()[0].article
    descriptor = next(item for item in article.mesh_descriptors if item.ui == "D000093742")

    assert descriptor.text == "Glucagon-Like Peptide-1 Receptor Agonists"
    assert descriptor.major_topic is True
    assert descriptor.supporting_pmid == article.pmid


def test_mesh_duplicate_merging_and_safe_links():
    result = normalize_medical_concepts(_ranked(), None, None)
    glp1 = next(item for item in result.normalized_concepts if item.concept_id == "D000093742")

    assert glp1.supporting_pmids == ("38521950", "38521990", "38522001")
    assert glp1.match_method == "source_metadata"
    assert all(link.relationship == ARTICLE_MENTIONS_CONCEPT for link in result.article_concept_links)
    assert all(link.evidence_level for link in result.article_concept_links)


def test_rxnorm_exact_match_creates_drug_without_collapsing_mesh_concept():
    rxnorm = StubRxNormClient((RxNormMatch("52175", "losartan", "IN", "exact"),))
    profile = _profile("obesity")
    result = normalize_medical_concepts(_ranked(), profile, rxnorm)

    drug = next(item for item in result.normalized_concepts if item.concept_id == "52175")
    assert drug.concept_type == "drug"
    assert drug.match_method == "exact"
    assert drug.confidence == 1.0
    assert rxnorm.terms == ["obesity"]  # accepted terms only


def test_unresolved_term_is_preserved_and_never_guessed_as_drug():
    result = normalize_medical_concepts(_ranked(), _profile(), StubRxNormClient(()))
    unresolved = next(item for item in result.normalized_concepts if item.concept_type == "unresolved")

    assert unresolved.original_term == "obesity"
    assert unresolved.concept_id.startswith("unresolved:")
    assert unresolved.confidence == 0.0
    assert all(item.concept_type != "drug" for item in result.normalized_concepts if item.concept_id == unresolved.concept_id)


def test_api_failure_warns_and_preserves_pubmed_concepts_and_term():
    result = normalize_medical_concepts(
        _ranked(),
        _profile(),
        StubRxNormClient(error=RuntimeError("service unavailable")),
    )

    assert any(item.vocabulary == "mesh" for item in result.normalized_concepts)
    assert any(item.concept_type == "unresolved" for item in result.normalized_concepts)
    assert "service unavailable" in result.warnings[0]


def test_outputs_include_concepts_and_only_supported_edge_type():
    result = normalize_medical_concepts(_ranked(), _profile(), StubRxNormClient(()))
    snapshot = build_snapshot("topic", "topic", NOW, ranked=_ranked(), profile=_profile(), concepts=result)
    markdown = build_markdown_report("topic", NOW, ranked=_ranked(), profile=_profile(), concepts=result)
    html = build_html_report("topic", NOW, ranked=_ranked(), profile=_profile(), concepts=result)

    assert snapshot["normalized_concepts"]
    assert snapshot["article_concept_links"]
    assert {link["relationship"] for link in snapshot["article_concept_links"]} == {ARTICLE_MENTIONS_CONCEPT}
    forbidden = {"TREATS", "CAUSES", "IMPROVES", "REDUCES_RISK", "ASSOCIATED_WITH"}
    assert forbidden.isdisjoint({link["relationship"] for link in snapshot["article_concept_links"]})
    assert "## Normalized medical concepts" in markdown
    assert "Normalized medical concepts" in html