"""Offline tests for exact-first, cache-backed RxNorm transport."""

import json
from pathlib import Path

from app.sources.rxnorm.client import RxNormClient

FIXTURES = Path(__file__).parent / "fixtures"


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeRxNormSession:
    def __init__(self, exact: dict, normalized: dict, properties: dict[str, dict]):
        self.exact = exact
        self.normalized = normalized
        self.properties = properties
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params, timeout))
        if url.endswith("/rxcui.json"):
            return FakeResponse(self.exact if params["search"] == 0 else self.normalized)
        rxcui = url.split("/rxcui/")[1].split("/")[0]
        return FakeResponse(self.properties[rxcui])


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_exact_match_uses_exact_lookup_and_properties(tmp_path):
    session = FakeRxNormSession(
        _fixture("rxnorm_exact.json"),
        _fixture("rxnorm_unresolved.json"),
        {"52175": _fixture("rxnorm_properties_52175.json")},
    )
    client = RxNormClient(session=session, cache_dir=tmp_path)

    matches = client.lookup("losartan")

    assert matches[0].rxcui == "52175"
    assert matches[0].name == "losartan"
    assert matches[0].match_method == "exact"
    assert [call[1]["search"] for call in session.calls if call[1]] == [0]


def test_normalized_match_preserves_distinct_official_rxcuis(tmp_path):
    session = FakeRxNormSession(
        _fixture("rxnorm_unresolved.json"),
        _fixture("rxnorm_normalized.json"),
        {
            "979494": _fixture("rxnorm_properties_979494.json"),
            "979492": _fixture("rxnorm_properties_979492.json"),
        },
    )
    matches = RxNormClient(session=session, cache_dir=tmp_path).lookup("Cozaar 50mg tablet")

    assert {match.rxcui for match in matches} == {"979494", "979492"}
    assert {match.tty for match in matches} == {"SBD", "SCD"}
    assert all(match.match_method == "normalized" for match in matches)
    assert [call[1]["search"] for call in session.calls if call[1]] == [0, 1]


def test_unresolved_result_is_cached_and_not_requested_twice(tmp_path):
    unresolved = _fixture("rxnorm_unresolved.json")
    session = FakeRxNormSession(unresolved, unresolved, {})
    client = RxNormClient(session=session, cache_dir=tmp_path)

    assert client.lookup("not a medicine") == ()
    first_call_count = len(session.calls)
    assert client.lookup("  NOT A MEDICINE ") == ()

    assert first_call_count == 2
    assert len(session.calls) == first_call_count
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_class_cache_keeps_only_structural_parent_relationships(tmp_path: Path):
    cache = tmp_path / "classes_2677894.json"
    cache.write_text(
        json.dumps(
            {
                "classes": [
                    {
                        "class_id": "A05BA",
                        "preferred_label": "Liver therapy",
                        "vocabulary": "ATC",
                        "relationship": "has_member",
                        "source_rxcui": "2677894",
                        "synonyms": [],
                    },
                    {
                        "class_id": "D065626",
                        "preferred_label": "Non-alcoholic Fatty Liver Disease",
                        "vocabulary": "MEDRT",
                        "relationship": "may_treat",
                        "source_rxcui": "2677894",
                        "synonyms": [],
                    },
                    {
                        "class_id": "N0000000237",
                        "preferred_label": "Thyroid Hormone Receptor Agonists",
                        "vocabulary": "MEDRT",
                        "relationship": "has_moa",
                        "source_rxcui": "2677894",
                        "synonyms": [],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    classes = RxNormClient(cache_dir=tmp_path).classes_for_rxcui("2677894")

    assert [(item.class_id, item.relationship) for item in classes] == [
        ("A05BA", "has_member")
    ]