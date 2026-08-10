"""Unit tests for the PubMed client using a fake transport (no network)."""

import json
from pathlib import Path

import pytest

from app.sources.pubmed.client import PubMedClient

FIXTURES = Path(__file__).parent / "fixtures"
ESEARCH_JSON = json.loads((FIXTURES / "esearch_sample.json").read_text(encoding="utf-8"))
EFETCH_XML = (FIXTURES / "efetch_sample.xml").read_text(encoding="utf-8")


class FakeResponse:
    """Minimal stand-in for ``requests.Response``."""

    def __init__(self, status_code: int, content: str | bytes):
        self.status_code = status_code
        self._content = content.encode("utf-8") if isinstance(content, str) else content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    @property
    def text(self) -> str:
        return self._content.decode("utf-8")

    def json(self) -> dict:
        return json.loads(self.text)


class FakeSession:
    """Records calls and returns canned responses keyed by endpoint."""

    def __init__(self, responses: dict[str, FakeResponse]):
        self.responses = responses
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, params: dict | None = None, timeout: int | None = None):
        self.calls.append((url, params or {}))
        endpoint = url.split("/")[-1]
        return self.responses[endpoint]


@pytest.fixture
def client():
    session = FakeSession(
        {
            "esearch.fcgi": FakeResponse(200, json.dumps(ESEARCH_JSON)),
            "esummary.fcgi": FakeResponse(200, json.dumps({"result": {}})),
            "efetch.fcgi": FakeResponse(200, EFETCH_XML),
        }
    )
    return PubMedClient(session=session, poll_delay=0)


def test_esearch_returns_idlist(client):
    pmids = client.esearch("GLP-1-based therapies", retmax=10)
    assert pmids == ["38522001", "38521990", "38521950"]


def test_esearch_sends_sort_pub_date(client):
    client.esearch("GLP-1-based therapies", retmax=10)
    url, params = client.session.calls[0]
    assert url.endswith("esearch.fcgi")
    assert params["db"] == "pubmed"
    assert params["term"] == "GLP-1-based therapies"
    assert params["retmax"] == 10
    assert params["sort"] == "pub_date"
    assert params["retmode"] == "json"


def test_esearch_empty_idlist(client):
    session = FakeSession(
        {"esearch.fcgi": FakeResponse(200, json.dumps({"esearchresult": {"idlist": []}}))}
    )
    empty_client = PubMedClient(session=session, poll_delay=0)
    assert empty_client.esearch("nothing") == []


def test_efetch_returns_xml_text(client):
    xml = client.efetch(["38522001", "38521990"])
    assert xml.startswith("<?xml")
    assert "<PubmedArticleSet>" in xml
    url, params = client.session.calls[0]
    assert url.endswith("efetch.fcgi")
    assert params["id"] == "38522001,38521990"
    assert params["rettype"] == "abstract"
    assert params["retmode"] == "xml"


def test_esummary_available_but_not_used_in_orchestration(client):
    data = client.esummary(["38522001"])
    assert data == {"result": {}}
    url, params = client.session.calls[0]
    assert url.endswith("esummary.fcgi")
    assert params["id"] == "38522001"
    assert params["retmode"] == "json"


def test_http_error_raises():
    session = FakeSession({"esearch.fcgi": FakeResponse(500, "error")})
    client = PubMedClient(session=session, poll_delay=0)
    with pytest.raises(RuntimeError):
        client.esearch("boom")