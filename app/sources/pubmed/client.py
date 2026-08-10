"""PubMed EUtils client: ESearch, ESummary, and EFetch.

The client is transport-agnostic: it accepts an injectable ``requests.Session``
(or any object with a compatible ``get()`` method) so tests can substitute a
fake without touching the network.
"""

from __future__ import annotations

import time

import requests

DEFAULT_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
DEFAULT_POLL_DELAY = 0.34  # seconds between outbound calls (NCBI politeness)


class PubMedClient:
    """Thin wrapper around the NCBI EUtils API."""

    def __init__(
        self,
        session: requests.Session | None = None,
        base_url: str = DEFAULT_BASE_URL,
        poll_delay: float = DEFAULT_POLL_DELAY,
    ) -> None:
        self.session = session or requests.Session()
        self.base_url = base_url.rstrip("/")
        self.poll_delay = poll_delay

    def esearch(self, term: str, retmax: int = 10) -> list[str]:
        """Return a list of PMIDs matching ``term``, newest first."""
        params = {
            "db": "pubmed",
            "term": term,
            "retmax": retmax,
            "sort": "pub_date",
            "retmode": "json",
        }
        data = self._get_json("esearch.fcgi", params)
        return data.get("esearchresult", {}).get("idlist", [])

    def esummary(self, pmids: list[str]) -> dict:
        """Return ESummary JSON metadata for the given PMIDs.

        Available for future use; not part of the primary retrieval path.
        """
        params = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "json",
        }
        return self._get_json("esummary.fcgi", params)

    def efetch(self, pmids: list[str]) -> str:
        """Return the raw EFetch XML document for the given PMIDs."""
        params = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "rettype": "abstract",
            "retmode": "xml",
        }
        return self._get_text("efetch.fcgi", params)

    def _get_json(self, endpoint: str, params: dict) -> dict:
        response = self._get(endpoint, params)
        return response.json()

    def _get_text(self, endpoint: str, params: dict) -> str:
        response = self._get(endpoint, params)
        return response.text

    def _get(self, endpoint: str, params: dict) -> requests.Response:
        url = f"{self.base_url}/{endpoint}"
        response = self.session.get(url, params=params, timeout=30)
        response.raise_for_status()
        time.sleep(self.poll_delay)
        return response