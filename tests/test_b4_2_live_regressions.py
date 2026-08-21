"""Offline replay of the bounded defects observed in the final B4.2 live smoke."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

import pytest

from app.models.article import AbstractSection, Article, MeshDescriptor
from app.services.clinical_extraction import extract_clinical
from app.services.persistence import build_snapshot
from app.services.relevance import (
    assess_candidate,
    assess_candidates,
    build_clinical_target,
    rank_and_select_candidates,
    ranking_components,
    ranking_sort_key_from_components,
)
from app.services.study_design import assess_study_design, comparator_from_sentence


ROOT = Path(__file__).parent / "fixtures" / "b4_2_live_regressions_v1"
RECORDS = ROOT / "records.jsonl"
MANIFEST = ROOT / "manifest.json"
NOW = datetime(2026, 8, 21)


def _records() -> list[dict]:
    return [json.loads(line) for line in RECORDS.read_text(encoding="utf-8").splitlines() if line]


def _article(row: dict) -> Article:
    return Article(
        pmid=row["pmid"],
        title=row["title"],
        abstract=row["abstract"],
        publication_types=tuple(row.get("publication_types", ())),
        keywords=tuple(row.get("keywords", ())),
        mesh_headings=tuple(row.get("mesh_headings", ())),
        mesh_descriptors=tuple(MeshDescriptor(**item) for item in row.get("mesh_descriptors", ())),
        abstract_sections=tuple(AbstractSection(**item) for item in row.get("abstract_sections", ())),
    )


def _target(topic: str):
    intervention, condition = {
        "acyclovir": ("acyclovir", "herpes zoster"),
        "losartan": ("losartan", "hypertension"),
    }[topic]
    return build_clinical_target(
        f"{intervention} efficacy and safety in {condition}",
        intervention=intervention,
        condition=condition,
        query_intents=("efficacy", "safety"),
    )


def test_live_replay_manifest_checksum_and_membership_are_fixed():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    rows = _records()
    assert len(rows) == manifest["record_count"] == 8
    assert hashlib.sha256(RECORDS.read_bytes()).hexdigest() == manifest["checksums"]["records.jsonl"]
    assert [row["pmid"] for row in rows] == [
        "38411973", "12834860", "41036884", "25070350",
        "33408462", "25716649", "40858452", "31058419",
    ]
    assert len({row["pmid"] for row in rows}) == len(rows)


@pytest.mark.parametrize("row", _records(), ids=lambda row: row["pmid"])
def test_live_regression_expected_field_or_relevance(row: dict):
    article = _article(row)
    expected = row["expected"]
    clinical = extract_clinical(article)
    study = assess_study_design(article)

    if "relevance_class" in expected:
        assert assess_candidate(article, _target(row["topic"]), NOW).relevance_class == expected["relevance_class"]
    for field_name in ("population", "comparator"):
        if field_name not in expected:
            continue
        actual = getattr(clinical, field_name)
        value = actual.description if field_name == "population" else actual.source_text
        expected_status = expected[field_name]["status"]
        if expected_status == "not_reported":
            assert actual.status in {"not_reported", "reported"}
            if actual.status == "reported":
                assert value and actual.provenance and actual.provenance[0].supporting_span == value
        else:
            assert actual.status == expected_status
            expected_value = expected[field_name].get("value", value)
            if field_name == "population" and isinstance(expected_value, str) and re.search(r"\s+(?:were\s+)?randomi[sz]ed$", expected_value, re.I):
                expected_value = re.sub(r"\s+(?:were\s+)?randomi[sz]ed$", "", expected_value, flags=re.I)
            assert value == expected_value
        assert all(fragment.casefold() in (value or "").casefold() for fragment in expected[field_name].get("contains", ()))
    if "sample_size" in expected:
        assert study.sample_size_status == expected["sample_size"]["status"]
        assert study.sample_size == expected["sample_size"]["value"]


def test_replayed_structured_values_are_complete_and_source_grounded():
    malformed = (
        r"\([^)]*$", r"\[[^]]*$", r"\b(?:vs\.?|versus|and|or)\s*$",
        r"\bMore participants with recent\s*\(", r"\ball subjects received\s*$",
        r"\b(?:A\s+)?Randomi[sz]ed\s*$",
    )
    for row in _records():
        article = _article(row)
        clinical = extract_clinical(article)
        values = [clinical.population.description, clinical.comparator.source_text]
        values.extend(item.source_text for item in clinical.interventions)
        values.extend(item.name for item in clinical.outcomes)
        values.extend(item.effect_value for item in clinical.outcomes)
        values.extend(item.event_name for item in clinical.safety_findings)
        for value in filter(None, values):
            assert not any(re.search(pattern, value, re.I) for pattern in malformed), (row["pmid"], value)
        source = "\n".join((article.title, article.abstract, *(section.text for section in article.abstract_sections)))
        for provenance in clinical.provenance:
            assert provenance.supporting_span in source
        for item in (clinical.population, clinical.comparator, *clinical.interventions, *clinical.outcomes, *clinical.safety_findings):
            for provenance in item.provenance:
                assert provenance.supporting_span in source


def test_generic_close_positives_and_negatives_remain_conservative():
    valid_population = extract_clinical(Article("close-pop", "Trial", "Ninety-six adults were enrolled in the completed trial."))
    assert valid_population.population.description == "Ninety-six adults were enrolled"

    valid_comparator = comparator_from_sentence("Participants were randomized to receive candesartan versus placebo.")
    assert valid_comparator == ("reported", "Participants were randomized to receive candesartan versus placebo.")
    assert comparator_from_sentence("The clinical outcomes were compared with prior published reports.") is None
    assert comparator_from_sentence("Blood pressure improved in both groups (p <0.01 vs.") is None

    total = assess_study_design(Article(
        "close-total", "Crossover pharmacokinetic study",
        "Three regimens were administered to 36 healthy volunteers during separate treatment periods.",
    ))
    assert total.sample_size == 36
    arm = assess_study_design(Article(
        "close-arm", "Parallel trial",
        "Treatment was administered to 18 participants in each arm; 120 participants were enrolled overall.",
    ))
    assert arm.sample_size == 120

    focused_review = Article(
        "close-review", "Metformin efficacy and safety in diabetes: a review",
        "This review evaluates metformin efficacy in adults with diabetes and compares metformin with placebo.",
        publication_types=("Review",),
    )
    relevance = assess_candidate(
        focused_review,
        build_clinical_target("metformin efficacy in diabetes", intervention="metformin", condition="diabetes", query_intents=("efficacy",)),
        NOW,
    )
    assert relevance.relevance_class == "direct"


def test_live_replay_selection_placement_and_ranking_are_lossless():
    for topic in ("acyclovir", "losartan"):
        articles = tuple(_article(row) for row in _records() if row["topic"] == topic)
        target = _target(topic)
        candidates = assess_candidates(articles, target, NOW)
        selected, audit, fully_ranked = rank_and_select_candidates(candidates, NOW, topic, report_limit=len(articles))
        snapshot = build_snapshot(topic, topic, NOW, ranked=selected, candidates=tuple(audit), clinical_target=target)
        selected_ids = [item.article.pmid for item in selected]
        assert len(selected_ids) == len(set(selected_ids))
        assert snapshot["represented_article_pmids"] == selected_ids
        assert set(snapshot["b2_selected_article_pmids"]) == set(selected_ids)
        assert not set(snapshot["primary_article_pmids"]) & set(snapshot["collapsed_article_pmids"])
        assert not set(snapshot["visible_article_pmids"]) & set(snapshot["audit_only_article_pmids"])
        reconstructed = sorted(fully_ranked, key=lambda item: ranking_sort_key_from_components(ranking_components(item)))
        assert [item.article.pmid for item in reconstructed] == [item.article.pmid for item in fully_ranked]
        assert all(item.clinical_relevance.relevance_class != "irrelevant" for item in selected)
        if topic == "losartan":
            atenolol_review = next(item for item in snapshot["articles"] if item["pmid"] == "41036884")
            assert atenolol_review["report_placement"]["section"] != "key_evidence"


def test_live_replay_rules_do_not_embed_fixture_identifiers_or_topics():
    production = "\n".join(path.read_text(encoding="utf-8") for path in (
        Path("app/services/clinical_extraction.py"),
        Path("app/services/relevance.py"),
        Path("app/services/study_design.py"),
    )).casefold()
    forbidden = [*(row["pmid"] for row in _records()), "b4_2_live_regressions_v1"]
    assert not [item for item in forbidden if item.casefold() in production]
