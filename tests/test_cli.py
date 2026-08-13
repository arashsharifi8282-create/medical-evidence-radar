"""End-to-end slice test: ESearch -> EFetch -> normalize -> rank, no network."""

import json
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from app.services.persistence import build_html_report, build_markdown_report, build_snapshot
from app.sources.pubmed.cli import fetch_top_recent, run_relevance_pipeline, save_results
from app.sources.pubmed.client import PubMedClient
from app.sources.rxnorm.client import RxNormClient
from app.sources.rxnorm.client import RxNormMatch
from app.services.evidence import rank_articles

FIXTURES = Path(__file__).parent / "fixtures"
ESEARCH_JSON = json.loads((FIXTURES / "esearch_sample.json").read_text(encoding="utf-8"))
EFETCH_XML = (FIXTURES / "efetch_sample.xml").read_text(encoding="utf-8")


class FakeResponse:
    def __init__(self, status_code: int, content: str):
        self.status_code = status_code
        self._content = content.encode("utf-8")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    @property
    def text(self) -> str:
        return self._content.decode("utf-8")

    def json(self) -> dict:
        return json.loads(self.text)


class FakeSession:
    def __init__(self, responses: dict[str, FakeResponse]):
        self.responses = responses
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, params: dict | None = None, timeout: int | None = None):
        self.calls.append((url, params or {}))
        endpoint = url.split("/")[-1]
        return self.responses[endpoint]


class FakeRxClassResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def json(self):
        return self.payload

    def raise_for_status(self):
        return None


class FakeRxNormSession:
    def __init__(self, matches: dict[str, tuple[RxNormMatch, ...]], classes: dict[tuple[str, str], list[dict]]):
        self.matches = matches
        self.classes = classes

    def get(self, url: str, params: dict | None = None, timeout: int | None = None):
        params = params or {}
        if url.endswith("/rxcui.json"):
            ids = [match.rxcui for match in self.matches.get(params.get("name", ""), ())]
            return FakeRxClassResponse({"idGroup": {"rxnormId": ids}})
        if "/rxcui/" in url and url.endswith("/properties.json"):
            rxcui = url.split("/rxcui/")[1].split("/")[0]
            match = next(
                item
                for matches in self.matches.values()
                for item in matches
                if item.rxcui == rxcui
            )
            return FakeRxClassResponse({"properties": {"name": match.name, "tty": match.tty}})
        if url.endswith("/rxclass/class/byRxcui.json"):
            entries = self.classes.get((str(params.get("rxcui")), str(params.get("relaSource"))), [])
            return FakeRxClassResponse({"rxclassDrugInfoList": {"rxclassDrugInfo": entries}})
        raise AssertionError(f"Unexpected RxNorm URL: {url}")


def _make_client() -> PubMedClient:
    session = FakeSession(
        {
            "esearch.fcgi": FakeResponse(200, json.dumps(ESEARCH_JSON)),
            "efetch.fcgi": FakeResponse(200, EFETCH_XML),
        }
    )
    return PubMedClient(session=session, poll_delay=0)


def _pipeline_pubmed_client(records: list[dict]) -> PubMedClient:
    idlist = [record["pmid"] for record in records]
    session = FakeSession(
        {
            "esearch.fcgi": FakeResponse(
                200,
                json.dumps({"esearchresult": {"count": str(len(idlist)), "idlist": idlist}}),
            ),
            "efetch.fcgi": FakeResponse(200, _pubmed_xml(records)),
        }
    )
    return PubMedClient(session=session, poll_delay=0)


def _pubmed_xml(records: list[dict]) -> str:
    return "<PubmedArticleSet>" + "".join(_article_xml(record) for record in records) + "</PubmedArticleSet>"


def _article_xml(record: dict) -> str:
    mesh_xml = "".join(
        f'<MeshHeading><DescriptorName UI="{escape(ui)}" MajorTopicYN="{major}">{escape(text)}</DescriptorName></MeshHeading>'
        for text, ui, major in record.get("mesh", ())
    )
    keyword_xml = "".join(f"<Keyword>{escape(keyword)}</Keyword>" for keyword in record.get("keywords", ()))
    type_xml = "".join(
        f"<PublicationType>{escape(publication_type)}</PublicationType>"
        for publication_type in record.get("types", ("Journal Article",))
    )
    abstract_xml = "".join(
        f'<AbstractText Label="{escape(label)}">{escape(text)}</AbstractText>'
        for label, text in record.get("abstract_sections", (("", record.get("abstract", "")),))
        if text
    )
    return f"""
<PubmedArticle>
  <MedlineCitation>
    <PMID>{escape(record['pmid'])}</PMID>
    <Article>
      <Journal><Title>{escape(record.get('journal', 'Fixture Journal'))}</Title><JournalIssue><PubDate><Year>2026</Year><Month>Aug</Month><Day>01</Day></PubDate></JournalIssue></Journal>
      <ArticleTitle>{escape(record['title'])}</ArticleTitle>
      <Abstract>{abstract_xml}</Abstract>
      <PublicationTypeList>{type_xml}</PublicationTypeList>
    </Article>
    <MeshHeadingList>{mesh_xml}</MeshHeadingList>
    <KeywordList>{keyword_xml}</KeywordList>
  </MedlineCitation>
  <PubmedData><ArticleIdList><ArticleId IdType="doi">10.0000/{escape(record['pmid'])}</ArticleId></ArticleIdList></PubmedData>
</PubmedArticle>
"""


def _rxclass_entry(class_id: str, label: str, source: str, relationship: str, synonyms=()) -> dict:
    return {
        "rxclassMinConceptItem": {"classId": class_id, "className": label},
        "relaSource": source,
        "rela": relationship,
        "classSynonyms": list(synonyms),
    }


def _rxnorm_client(tmp_path: Path, *, include_structural_class: bool, include_unapproved_class: bool = False) -> RxNormClient:
    classes: dict[tuple[str, str], list[dict]] = {}
    if include_structural_class:
        classes[("1991302", "MEDRT")] = [
            _rxclass_entry(
                "N0000175842",
                "Glucagon-Like Peptide-1 Receptor Agonists",
                "MEDRT",
                "has_member",
                ("GLP-1 receptor agonists", "GLP-1 RAs"),
            )
        ]
    if include_unapproved_class:
        classes[("1991302", "MEDRT")] = classes.get(("1991302", "MEDRT"), []) + [
            _rxclass_entry("D019440", "Anti-Obesity Agents", "MEDRT", "may_treat")
        ]
    session = FakeRxNormSession(
        {
            "semaglutide": (RxNormMatch("1991302", "semaglutide", "IN", "exact"),),
            "semaglutide OR tirzepatide": (
                RxNormMatch("1991302", "semaglutide", "IN", "exact"),
                RxNormMatch("226552", "tirzepatide", "IN", "exact"),
            ),
        },
        classes,
    )
    return RxNormClient(session=session, cache_dir=tmp_path)


def test_fetch_top_recent_returns_normalized_articles():
    client = _make_client()
    articles = fetch_top_recent(query="GLP-1-based therapies", retmax=3, client=client)

    assert len(articles) == 3
    assert articles[0].pmid == "38522001"
    assert articles[0].title.startswith("Cardiovascular outcomes")
    assert articles[0].publication_date_raw == "2024 Jun"
    assert articles[0].publication_date is not None
    assert articles[0].pubmed_url == "https://pubmed.ncbi.nlm.nih.gov/38522001/"
    assert articles[0].mesh_headings  # MeSH headings extracted
    assert articles[0].keywords  # author keywords extracted


def test_fetch_top_recent_uses_esearch_then_efetch_only():
    client = _make_client()
    fetch_top_recent(query="GLP-1-based therapies", retmax=3, client=client)

    endpoints = [url.split("/")[-1] for url, _ in client.session.calls]
    assert endpoints == ["esearch.fcgi", "efetch.fcgi"]
    # ESummary must NOT be called in the orchestration path.
    assert "esummary.fcgi" not in endpoints


def test_fetch_top_recent_empty_idlist_returns_empty():
    session = FakeSession(
        {"esearch.fcgi": FakeResponse(200, json.dumps({"esearchresult": {"idlist": []}}))}
    )
    client = PubMedClient(session=session, poll_delay=0)
    assert fetch_top_recent(query="nothing", retmax=10, client=client) == []


def test_save_results_writes_json_markdown_html_and_profile(tmp_path: Path):
    client = _make_client()
    articles = fetch_top_recent(query="GLP-1-based therapies", retmax=3, client=client)
    fetched_at = datetime(2026, 8, 10, 9, 30, 0)
    ranked = rank_articles(articles, fetched_at, topic="GLP-1-based therapies")

    json_dir = tmp_path / "data" / "raw" / "pubmed"
    md_dir = tmp_path / "reports" / "pubmed"
    html_dir = tmp_path / "reports" / "pubmed"
    profile_dir = tmp_path / "data" / "topic_profiles"

    json_path, md_path, html_path, profile_path = save_results(
        ranked,
        topic="GLP-1-based therapies",
        query="GLP-1-based therapies",
        fetched_at=fetched_at,
        json_dir=json_dir,
        md_dir=md_dir,
        html_dir=html_dir,
        profile_dir=profile_dir,
    )

    # All four files exist with query-based names.
    assert json_path.exists()
    assert md_path.exists()
    assert html_path.exists()
    assert profile_path.exists()
    assert json_path.name == "glp_1_based_therapies.json"
    assert md_path.name == "glp_1_based_therapies.md"
    assert html_path.name == "glp_1_based_therapies.html"
    assert profile_path.name == "glp_1_based_therapies.json"

    # JSON content.
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["topic"] == "GLP-1-based therapies"
    assert data["query"] == "GLP-1-based therapies"
    assert data["fetched_at"] == "2026-08-10T09:30:00"
    assert len(data["articles"]) == 3
    assert data["articles"][0]["pmid"] == "38522001"
    assert "assessment" in data["articles"][0]
    assert data["articles"][0]["assessment"]["evidence_level"] == "systematic_review"
    assert "discovered_terms" in data
    assert "accepted" in data["discovered_terms"]
    assert "rejected" in data["discovered_terms"]

    # Markdown content.
    text = md_path.read_text(encoding="utf-8")
    assert "# PubMed Report: GLP-1-based therapies" in text
    assert "**Fetch timestamp:** 2026-08-10T09:30:00" in text
    assert "Cardiovascular outcomes with GLP-1 receptor agonists" in text
    assert "**Evidence level:**" in text
    assert "**Evidence score:**" in text
    assert "**Why included:**" in text
    assert "**Limitations:**" in text
    assert "## Discovered terms" in text
    assert "## Key evidence" in text

    # HTML content.
    html_text = html_path.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in html_text
    assert "PubMed Report: GLP-1-based therapies" in html_text
    assert "2026-08-10T09:30:00" in html_text
    assert "Cardiovascular outcomes with GLP-1 receptor agonists" in html_text
    assert "Evidence level:" in html_text
    assert "Why included:" in html_text
    assert "Limitations:" in html_text
    assert "Discovered terms" in html_text
    assert "Key evidence" in html_text

    # Topic profile content.
    profile_data = json.loads(profile_path.read_text(encoding="utf-8"))
    assert profile_data["topic"] == "GLP-1-based therapies"
    assert profile_data["query"] == "GLP-1-based therapies"
    assert "accepted_terms" in profile_data
    assert "rejected_terms" in profile_data


def test_save_results_uses_query_filenames_and_timestamp_on_collision(tmp_path: Path):
    client = _make_client()
    articles = fetch_top_recent(query="GLP-1-based therapies", retmax=3, client=client)

    json_dir = tmp_path / "data" / "raw" / "pubmed"
    md_dir = tmp_path / "reports" / "pubmed"
    html_dir = tmp_path / "reports" / "pubmed"
    profile_dir = tmp_path / "data" / "topic_profiles"

    ranked1 = rank_articles(articles, datetime(2026, 8, 10, 9, 30, 0), topic="GLP-1-based therapies")
    ranked2 = rank_articles(articles, datetime(2026, 8, 10, 10, 0, 0), topic="GLP-1-based therapies")

    json_path1, md_path1, html_path1, _ = save_results(
        ranked1,
        fetched_at=datetime(2026, 8, 10, 9, 30, 0),
        json_dir=json_dir,
        md_dir=md_dir,
        html_dir=html_dir,
        profile_dir=profile_dir,
    )
    json_path2, md_path2, html_path2, _ = save_results(
        ranked2,
        fetched_at=datetime(2026, 8, 10, 10, 0, 0),
        json_dir=json_dir,
        md_dir=md_dir,
        html_dir=html_dir,
        profile_dir=profile_dir,
    )

    assert json_path1.name == "glp_1_based_therapies.json"
    assert json_path2.name == "glp_1_based_therapies_20260810_100000.json"
    assert md_path1.name == "glp_1_based_therapies.md"
    assert md_path2.name == "glp_1_based_therapies_20260810_100000.md"
    assert html_path1.name == "glp_1_based_therapies.html"
    assert html_path2.name == "glp_1_based_therapies_20260810_100000.html"
    assert json_path1 != json_path2
    assert md_path1 != md_path2
    assert html_path1 != html_path2


def test_relevance_pipeline_orchestrates_target_rxclass_assessment_ranking_and_outputs(tmp_path: Path):
    fetched_at = datetime(2026, 8, 13, 12, 0, 0)
    records = [
        {
            "pmid": "9001",
            "title": "Semaglutide safety in obesity: randomized trial",
            "abstract_sections": (("RESULTS", "Semaglutide adverse events in obesity patients were compared."),),
            "mesh": (("Semaglutide", "D000099194", "N"), ("Obesity", "D009765", "Y"), ("Humans", "D006801", "N")),
            "keywords": ("semaglutide", "obesity"),
            "types": ("Randomized Controlled Trial", "Journal Article"),
        },
        {
            "pmid": "9002",
            "title": "Clinical obesity management review",
            "abstract": "Background: obesity care may include semaglutide as one therapeutic option in selected patients.",
            "mesh": (("Obesity", "D009765", "Y"), ("Humans", "D006801", "N")),
            "types": ("Review", "Journal Article"),
        },
        {
            "pmid": "9003",
            "title": "Semaglutide safety in obese mice",
            "abstract": "Animal model adverse events in mice were evaluated.",
            "mesh": (("Semaglutide", "D000099194", "N"), ("Obesity", "D009765", "N"), ("Mice", "D051379", "Y")),
        },
        {
            "pmid": "9004",
            "title": "GLP-1 receptor agonists safety in obesity",
            "abstract": "Adverse events across GLP-1 receptor agonists were summarized in human obesity treatment.",
            "mesh": (("Obesity", "D009765", "Y"), ("Humans", "D006801", "N")),
            "keywords": ("GLP-1 RAs",),
            "types": ("Systematic Review", "Review"),
        },
        {
            "pmid": "9005",
            "title": "Digital pathology AI for obesity trials",
            "abstract": "Machine learning imaging is an emerging research trend; semaglutide is mentioned as background context in obesity trials.",
            "mesh": (("Obesity", "D009765", "Y"), ("Humans", "D006801", "N")),
            "keywords": ("artificial intelligence",),
            "types": ("Review", "Journal Article"),
        },
    ]
    run = run_relevance_pipeline(
        "semaglutide safety and adverse effects in obesity",
        intervention="semaglutide",
        condition="obesity",
        candidate_limit=10,
        report_limit=10,
        fetched_at=fetched_at,
        pubmed_client=_pipeline_pubmed_client(records),
        rxnorm_client=_rxnorm_client(tmp_path, include_structural_class=True),
    )

    by_pmid = {item.article.pmid: item.relevance for item in run.candidates}
    assert run.target.intervention_term == "semaglutide"
    assert run.target.condition_term == "obesity"
    assert run.target.intervention_rxcuis == ("1991302",)
    assert run.target.query_intents == ("safety",)
    assert [(item.vocabulary, item.relationship) for item in run.target.confirmed_classes] == [("MEDRT", "has_member")]
    assert by_pmid["9001"].relevance_class == "direct"
    assert by_pmid["9002"].relevance_class == "contextual"
    assert by_pmid["9003"].relevance_class == "irrelevant"
    assert by_pmid["9004"].relevance_class == "class_level"
    assert by_pmid["9005"].relevance_class == "contextual"
    assert by_pmid["9005"].content_role == "research_enabler"
    assert [item.article.pmid for item in run.ranked[:2]] == ["9001", "9004"]
    assert {item.article.pmid for item in run.ranked[2:]} == {"9002", "9005"}
    assert run.search_quality.direct_count == 1
    assert run.search_quality.class_level_count == 1
    assert run.search_quality.contextual_count == 2
    assert run.search_quality.irrelevant_count == 1

    snapshot = build_snapshot(
        run.retrieval.query,
        run.retrieval.query,
        fetched_at,
        ranked=list(run.ranked),
        candidates=run.candidates,
        clinical_target=run.target,
        search_quality=run.search_quality,
    )
    markdown = build_markdown_report(run.retrieval.query, fetched_at, list(run.ranked), search_quality=run.search_quality)
    html = build_html_report(run.retrieval.query, fetched_at, list(run.ranked), search_quality=run.search_quality)

    assert snapshot["clinical_target"]["query_intents"] == ["safety"]
    assert next(item for item in snapshot["articles"] if item["pmid"] == "9005")["clinical_relevance"]["content_role"] == "research_enabler"
    assert "Emerging mechanisms and research trends" in markdown
    assert "Content role:</span> <span class=\"meta-value\">research_enabler" in html
    assert "Semaglutide safety in obese mice" not in markdown
    assert "Semaglutide safety in obese mice" not in html


def test_unapproved_rxclass_relationship_does_not_become_class_level(tmp_path: Path):
    record = {
        "pmid": "9010",
        "title": "Anti-Obesity Agents safety in obesity",
        "abstract": "Adverse event reports for anti-obesity agents in human obesity care.",
        "mesh": (("Obesity", "D009765", "Y"), ("Humans", "D006801", "N")),
        "types": ("Review", "Journal Article"),
    }
    run = run_relevance_pipeline(
        "semaglutide safety and adverse effects in obesity",
        intervention="semaglutide",
        condition="obesity",
        candidate_limit=5,
        report_limit=5,
        fetched_at=datetime(2026, 8, 13, 12, 5, 0),
        pubmed_client=_pipeline_pubmed_client([record]),
        rxnorm_client=_rxnorm_client(tmp_path, include_structural_class=False, include_unapproved_class=True),
    )

    assert run.target.confirmed_classes == ()
    assert run.candidates[0].relevance.relevance_class == "contextual"
    assert run.search_quality.class_level_count == 0


def test_multi_intervention_or_target_remains_complete_through_pipeline(tmp_path: Path):
    record = {
        "pmid": "9020",
        "title": "Semaglutide and tirzepatide safety in obesity",
        "abstract_sections": (("RESULTS", "Semaglutide and tirzepatide adverse events in obesity patients were compared."),),
        "mesh": (("Obesity", "D009765", "Y"), ("Humans", "D006801", "N")),
    }
    run = run_relevance_pipeline(
        "semaglutide OR tirzepatide safety in obesity",
        intervention="semaglutide OR tirzepatide",
        condition="obesity",
        candidate_limit=5,
        report_limit=5,
        fetched_at=datetime(2026, 8, 13, 12, 10, 0),
        pubmed_client=_pipeline_pubmed_client([record]),
        rxnorm_client=_rxnorm_client(tmp_path, include_structural_class=False),
    )

    assert run.target.intervention_logic == "OR"
    assert run.target.intervention_rxcuis == ("1991302", "226552")
    assert run.target.intervention_labels == ("semaglutide", "tirzepatide")
    assert run.target.target_interventions == ("semaglutide", "tirzepatide")
    assert run.candidates[0].relevance.relevance_class == "direct"