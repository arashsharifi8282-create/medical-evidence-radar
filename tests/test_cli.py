"""End-to-end slice test: ESearch -> EFetch -> normalize -> rank, no network."""

import json
from datetime import datetime
from pathlib import Path

from app.sources.pubmed.cli import fetch_top_recent, save_results
from app.sources.pubmed.client import PubMedClient
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


def _make_client() -> PubMedClient:
    session = FakeSession(
        {
            "esearch.fcgi": FakeResponse(200, json.dumps(ESEARCH_JSON)),
            "efetch.fcgi": FakeResponse(200, EFETCH_XML),
        }
    )
    return PubMedClient(session=session, poll_delay=0)


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

    # All four files exist with timestamped names.
    assert json_path.exists()
    assert md_path.exists()
    assert html_path.exists()
    assert profile_path.exists()
    assert json_path.name == "pubmed_20260810_093000.json"
    assert md_path.name == "pubmed_20260810_093000.md"
    assert html_path.name == "pubmed_20260810_093000.html"
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


def test_save_results_uses_timestamped_filenames_no_overwrite(tmp_path: Path):
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

    assert json_path1.name == "pubmed_20260810_093000.json"
    assert json_path2.name == "pubmed_20260810_100000.json"
    assert md_path1.name == "pubmed_20260810_093000.md"
    assert md_path2.name == "pubmed_20260810_100000.md"
    assert html_path1.name == "pubmed_20260810_093000.html"
    assert html_path2.name == "pubmed_20260810_100000.html"
    assert json_path1 != json_path2
    assert md_path1 != md_path2
    assert html_path1 != html_path2