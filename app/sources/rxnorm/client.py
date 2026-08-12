"""Small, cache-backed client for the public NLM RxNorm API."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

import requests

from app.models.relevance import ConfirmedDrugClass

DEFAULT_BASE_URL = "https://rxnav.nlm.nih.gov/REST"
DEFAULT_CACHE_DIR = Path("data/cache/rxnorm")
APPROVED_CLASS_SOURCES = ("ATC", "MEDRT")
# Only structural membership/substance classification can support B2's parent
# class evidence. Indication, mechanism, physiologic-effect and ingredient
# relationships are valid RxClass facts, but are not parent drug classes.
APPROVED_PARENT_RELATIONSHIPS = frozenset({"has_member", "isa", "part_of"})


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

    def classes_for_rxcui(self, rxcui: str) -> tuple[ConfirmedDrugClass, ...]:
        """Return only official ATC/MED-RT parent classes, with local caching.

        If the public service is unavailable the caller should treat the class
        relationship as unconfirmed; no lexical or co-occurrence inference is
        performed here.
        """
        cache_path = self.cache_dir / f"classes_{rxcui}.json"
        if cache_path.exists():
            return self._decode_class_cache(cache_path)

        classes: list[ConfirmedDrugClass] = []
        for source in APPROVED_CLASS_SOURCES:
            response = self.session.get(
                f"{self.base_url}/rxclass/class/byRxcui.json",
                params={"rxcui": rxcui, "relaSource": source},
                timeout=30,
            )
            response.raise_for_status()
            entries = (
                response.json()
                .get("rxclassDrugInfoList", {})
                .get("rxclassDrugInfo", [])
                or []
            )
            for entry in entries:
                item = entry.get("rxclassMinConceptItem") or {}
                class_id = str(item.get("classId") or "").strip()
                label = str(item.get("className") or "").strip()
                if not class_id or not label:
                    continue
                relationship = str(entry.get("rela") or "").strip().casefold()
                if relationship not in APPROVED_PARENT_RELATIONSHIPS:
                    continue
                synonyms = tuple(
                    str(value).strip()
                    for value in entry.get("classSynonyms", []) or []
                    if str(value).strip()
                )
                classes.append(
                    ConfirmedDrugClass(
                        class_id=class_id,
                        preferred_label=label,
                        vocabulary=str(entry.get("relaSource") or source).upper(),
                        relationship=relationship,
                        source_rxcui=str(rxcui),
                        synonyms=synonyms,
                    )
                )

        unique = {
            (item.vocabulary, item.class_id, item.relationship): item for item in classes
        }
        result = tuple(
            sorted(unique.values(), key=lambda item: (item.vocabulary, item.preferred_label, item.class_id))
        )
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(
                {
                    "rxcui": str(rxcui),
                    "classes": [
                        {
                            "class_id": item.class_id,
                            "preferred_label": item.preferred_label,
                            "vocabulary": item.vocabulary,
                            "relationship": item.relationship,
                            "source_rxcui": item.source_rxcui,
                            "synonyms": list(item.synonyms),
                        }
                        for item in result
                    ],
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        return result

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

    @staticmethod
    def _decode_class_cache(path: Path) -> tuple[ConfirmedDrugClass, ...]:
        data = json.loads(path.read_text(encoding="utf-8"))
        return tuple(
            ConfirmedDrugClass(
                class_id=item["class_id"],
                preferred_label=item["preferred_label"],
                vocabulary=item["vocabulary"],
                relationship=item["relationship"],
                source_rxcui=item["source_rxcui"],
                synonyms=tuple(item.get("synonyms", [])),
            )
            for item in data.get("classes", [])
            if str(item.get("relationship", "")).casefold() in APPROVED_PARENT_RELATIONSHIPS
        )