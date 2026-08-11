"""Small, cache-backed client for the public NLM RxNorm API."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

import requests

DEFAULT_BASE_URL = "https://rxnav.nlm.nih.gov/REST"
DEFAULT_CACHE_DIR = Path("data/cache/rxnorm")


@dataclass(frozen=True)
class RxNormMatch:
    rxcui: str
    name: str
    tty: str
    match_method: str


class RxNormClient:
    """Resolve names with exact-first lookup and persistent response caching."""

    def __init__(
        self,
        session: requests.Session | None = None,
        base_url: str = DEFAULT_BASE_URL,
        cache_dir: Path = DEFAULT_CACHE_DIR,
    ) -> None:
        self.session = session or requests.Session()
        self.base_url = base_url.rstrip("/")
        self.cache_dir = cache_dir

    def lookup(self, term: str) -> tuple[RxNormMatch, ...]:
        cache_path = self._cache_path(term)
        if cache_path.exists():
            return self._decode_cached(cache_path)

        matches = self._lookup_mode(term, search=0, match_method="exact")
        if not matches:
            matches = self._lookup_mode(term, search=1, match_method="normalized")

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(
                {
                    "term": term,
                    "matches": [
                        {
                            "rxcui": match.rxcui,
                            "name": match.name,
                            "tty": match.tty,
                            "match_method": match.match_method,
                        }
                        for match in matches
                    ],
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        return matches

    def _lookup_mode(self, term: str, search: int, match_method: str) -> tuple[RxNormMatch, ...]:
        response = self.session.get(
            f"{self.base_url}/rxcui.json",
            params={"name": term, "search": search},
            timeout=30,
        )
        response.raise_for_status()
        ids = response.json().get("idGroup", {}).get("rxnormId") or []
        matches: list[RxNormMatch] = []
        for rxcui in dict.fromkeys(ids):
            properties_response = self.session.get(
                f"{self.base_url}/rxcui/{rxcui}/properties.json",
                timeout=30,
            )
            properties_response.raise_for_status()
            properties = properties_response.json().get("properties") or {}
            matches.append(
                RxNormMatch(
                    rxcui=str(rxcui),
                    name=properties.get("name") or term,
                    tty=properties.get("tty") or "",
                    match_method=match_method,
                )
            )
        return tuple(matches)

    def _cache_path(self, term: str) -> Path:
        normalized = re.sub(r"\s+", " ", term.strip().casefold())
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.json"

    @staticmethod
    def _decode_cached(path: Path) -> tuple[RxNormMatch, ...]:
        data = json.loads(path.read_text(encoding="utf-8"))
        return tuple(RxNormMatch(**match) for match in data.get("matches", []))