"""Offline Phase B1 concept identification and safety tests."""

from datetime import datetime
from pathlib import Path

from app.models.concept import ArticleConceptLink, ConceptNormalizationResult, NormalizedConcept
from app.models.topic_profile import CandidateTerm, TopicProfile
from app.services.concept_normalization import ARTICLE_MENTIONS_CONCEPT, normalize_medical_concepts
from app.services.evidence import rank_articles
from app.services.normalizer import normalize_article, parse_pubmed_articles
from app.services.persistence import build_concept_summary, build_html_report, build_markdown_report, build_snapshot
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
    assert "## Medical concept summary" in markdown
    assert "Medical concept summary" in html


def _candidate(term, score, df, overlap=0.0, accepted=True):
    return CandidateTerm(
        term=term,
        source="mesh",
        document_frequency=df,
        evidence_max="randomized_trial",
        recency_days=1,
        direct_topic_overlap=overlap,
        supporting_articles=tuple(str(i) for i in range(df)),
        score=score,
        reasons=(f"private reason for {term}",),
        accepted=accepted,
    )


def _concept(term, concept_id, pmid_count, *, unresolved=False):
    return NormalizedConcept(
        concept_id=concept_id,
        vocabulary="rxnorm",
        preferred_label=f"Preferred {term}",
        original_term=term,
        concept_type="unresolved" if unresolved else "drug",
        match_method="approximate" if unresolved else "exact",
        confidence=0.0 if unresolved else 1.0,
        supporting_pmids=tuple(str(i) for i in range(pmid_count)),
        source_fields=("mesh", "abstract"),
    )


def _phase_b11_fixture():
    accepted = tuple(
        [_candidate(f"core-{i}", 100 - i, 10 - i, overlap=1.0) for i in range(5)]
        + [_candidate(f"related-{i}", 90 - i, 8 - i) for i in range(7)]
    )
    rejected = tuple(_candidate(f"rejected-secret-{i}", 10, 1, accepted=False) for i in range(46))
    profile = TopicProfile("core-0 core-1 core-2 core-3 core-4", "query", NOW, accepted, rejected)
    normalized = tuple(
        [_concept(f"core-{i}", f"C{i}", 3) for i in range(5)]
        + [_concept(f"related-{i}", f"R{i}", 2 + (i % 2)) for i in range(7)]
        + [_concept("unresolved-secret", "unresolved:secret", 2, unresolved=True)]
        # Duplicate stable identity must never appear twice in the compact summary.
        + [_concept("related-0", "R0", 2)]
    )
    links = tuple(
        ArticleConceptLink(
            ARTICLE_MENTIONS_CONCEPT,
            pmid,
            concept.concept_id,
            "mesh",
            concept.match_method,
            concept.confidence,
            "randomized_trial",
        )
        for concept in normalized
        for pmid in concept.supporting_pmids
    )
    return profile, ConceptNormalizationResult(normalized, links, ("private warning",))


def test_compact_summary_caps_lists_and_has_no_duplicates():
    profile, concepts = _phase_b11_fixture()
    summary = build_concept_summary(profile.topic, profile, concepts)

    assert len(summary["core_concepts"]) == 3
    assert len(summary["related_concepts"]) == 5
    identities = [
        (item["vocabulary"], item["concept_id"])
        for item in summary["core_concepts"] + summary["related_concepts"]
    ]
    assert len(identities) == len(set(identities))
    assert summary["rejected_candidate_count"] == 46
    assert summary["unresolved_count"] == 1


def test_default_reports_hide_rejected_terms_and_individual_links():
    profile, concepts = _phase_b11_fixture()
    markdown = build_markdown_report(profile.topic, NOW, ranked=[], profile=profile, concepts=concepts)
    html = build_html_report(profile.topic, NOW, ranked=[], profile=profile, concepts=concepts)

    expected = "46 additional candidates were rejected during quality filtering."
    assert expected in markdown
    assert expected in html
    assert "rejected-secret-0" not in markdown
    assert "rejected-secret-0" not in html
    assert "relationship" not in markdown
    assert "ARTICLE_MENTIONS_CONCEPT" not in html
    assert f"{len(concepts.article_concept_links)} article-concept links" in markdown
    assert f"{len(concepts.article_concept_links)} article-concept links" in html


def test_full_audit_data_remains_in_snapshot_json():
    profile, concepts = _phase_b11_fixture()
    snapshot = build_snapshot(profile.topic, profile.query, NOW, ranked=[], profile=profile, concepts=concepts)

    assert len(snapshot["discovered_terms"]["rejected"]) == 46
    assert snapshot["discovered_terms"]["rejected"][0]["reasons"]
    assert len(snapshot["normalized_concepts"]) == len(concepts.normalized_concepts)
    assert len(snapshot["article_concept_links"]) == len(concepts.article_concept_links)
    assert snapshot["concept_normalization_warnings"] == ["private warning"]
    assert snapshot["concept_summary"]["total_links"] == len(concepts.article_concept_links)


def test_html_technical_and_unresolved_details_are_collapsed():
    profile, concepts = _phase_b11_fixture()
    html = build_html_report(profile.topic, NOW, ranked=[], profile=profile, concepts=concepts)

    assert '<details class="concept-details technical-concept-details">' in html
    assert '<summary>Technical concept details</summary>' in html
    assert '<details class="concept-details technical-concept-details" open>' not in html
    assert '<details class="concept-details unresolved-details">' in html
    assert "unresolved-secret" in html
    assert "Supporting PMIDs" in html