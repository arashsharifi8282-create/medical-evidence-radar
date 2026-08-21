"""Offline B4.2 multi-topic validation and integrity regressions."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

import pytest

from app.models.article import Article
from app.models.assessment import RankedArticle
from app.services.clinical_extraction import extract_clinical
from app.services.evidence import assess_article
from app.services.persistence import build_snapshot
from app.services.relevance import assess_candidate, build_clinical_target
from app.services.study_design import comparator_from_sentence
from tests.b4_2_evaluator import FIELDS, evaluate

ROOT = Path(__file__).parent / "fixtures" / "b4_2_multi_topic"
RECORDS = ROOT / "records.jsonl"
SOURCES = ROOT / "sources.jsonl"
GOLD = ROOT / "gold_labels.jsonl"
MANIFEST = ROOT / "manifest.json"
NOW = datetime(2026, 8, 21)


def _records():
    return [json.loads(line) for line in RECORDS.read_text(encoding="utf-8").splitlines() if line]


def _articles():
    from app.models.article import AbstractSection

    result = {}
    for row in (json.loads(line) for line in SOURCES.read_text(encoding="utf-8").splitlines() if line):
        result[row["pmid"]] = Article(
            row["pmid"],
            row["title"],
            row["abstract"],
            publication_types=tuple(row["publication_types"]),
            keywords=tuple(row["keywords"]),
            abstract_sections=tuple(AbstractSection(item.get("label", ""), item.get("text", "")) for item in row["abstract_sections"]),
        )
    return result


def test_benchmark_manifest_checksum_and_split_are_immutable():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    records = _records()
    assert len(records) == manifest["record_count"] == 24
    for path in (RECORDS, SOURCES, GOLD):
        assert hashlib.sha256(path.read_bytes()).hexdigest() == manifest["checksums"][path.name]
    assert {r["topic"] for r in records} == set(manifest["topics"])
    assert {r["split"] for r in records} == {"development", "holdout"}
    for split in ("development", "holdout"):
        assert {r["topic"] for r in records if r["split"] == split} == set(manifest["topics"])


def test_gold_labels_are_complete_scored_and_source_grounded():
    registry = _records()
    sources = [json.loads(line) for line in SOURCES.read_text(encoding="utf-8").splitlines() if line]
    gold = [json.loads(line) for line in GOLD.read_text(encoding="utf-8").splitlines() if line]
    registry_ids = [row["source_pmid"] for row in registry]
    source_ids = [row["pmid"] for row in sources]
    gold_ids = [row["pmid"] for row in gold]
    assert len(registry_ids) == len(set(registry_ids)) == 24
    assert set(registry_ids) == set(source_ids) == set(gold_ids)
    assert len(source_ids) == len(set(source_ids))
    assert len(gold_ids) == len(set(gold_ids))
    source_by_id = {row["pmid"]: row for row in sources}
    for label in gold:
        assert label["topic"] and label["split"] in {"development", "holdout"}
        assert label["relevance"]["scored"] is True
        assert label["relevance"]["scoring_reason"]
        assert label["relevance"]["adjudication_rationale"]
        assert label["study"]["scored"] is True
        assert label["study"]["scoring_reason"]
        assert label["study"]["adjudication_rationale"]
        assert set(label["fields"]) == set(FIELDS)
        source = source_by_id[label["pmid"]]
        source_text = "\n".join((source["title"], source["abstract"], *source["publication_types"], *(part.get("text", "") for part in source["abstract_sections"])))
        for name, field in label["fields"].items():
            assert field["status"]
            assert field["acceptable_statuses"]
            assert field["acceptable_values"]
            assert field["scored"] is True, f"{label['pmid']}:{name} was removed from its denominator"
            assert field["unscored_reason"] is None
            assert field["scoring_reason"]
            assert field["adjudication_rationale"]
            if field["status"] == "reported":
                assert field["supporting_source_span"] in source_text
                assert field["source_field"] and field["rule_id"]
            else:
                assert field["canonical_value"] is None
        condition_span = label["relevance"]["condition_supporting_span"]
        if label["relevance"]["requested_condition_support"]:
            assert condition_span in source_text
        else:
            assert condition_span is None


@pytest.mark.parametrize(
    "filters,expected_count",
    [
        ({"split": "development"}, 12),
        ({"split": "holdout"}, 12),
        ({"topic": "acyclovir_herpes_zoster"}, 12),
        ({"topic": "losartan_hypertension"}, 12),
    ],
)
def test_evaluator_thresholds_pass_by_split_and_topic(filters, expected_count):
    result = evaluate(filters)
    assert result["record_count"] == expected_count
    assert result["passed"], result
    assert result["critical"] == {
        "malformed": 0,
        "unsupported_effect": 0,
        "unsupported_safety": 0,
        "provenance_failures": 0,
    }


def test_overall_evaluator_is_deterministic_and_report_integrity_is_zero():
    first = evaluate()
    second = evaluate()
    assert first == second
    assert first["record_count"] == 24
    assert first["passed"], first
    assert not any(first["integrity"]["counts"].values())
    assert all(field["applicable"] == 24 for field in first["fields"].values())


def test_role_aware_relevance_and_method_sentence_abstention():
    target = build_clinical_target("drug efficacy in condition", intervention="drug", condition="condition", query_intents=("efficacy",))
    active = Article("role-active", "Drug trial in condition", "Patients were randomized to receive drug versus placebo. Results improved.")
    background = Article("role-background", "Other therapy in condition", "Drug produced plasma levels similar to the historical standard. Results improved.")
    assert assess_candidate(active, target, NOW).requested_intervention_role == "primary_intervention"
    assert assess_candidate(active, target, NOW).relevance_class == "direct"
    assert assess_candidate(background, target, NOW).requested_intervention_role == "pharmacokinetic_reference"
    assert assess_candidate(background, target, NOW).relevance_class != "direct"
    assert comparator_from_sentence("Databases were searched for trials comparing drug versus placebo.") is None
    review = extract_clinical(Article("review", "Review", "Secondary outcomes included adverse events. Databases were searched."))
    assert not review.safety_findings


def test_span_fields_are_source_grounded_and_persisted_without_raw_rewrite():
    abstract = "METHODS: 80 patients with condition were randomized to receive drug 10 mg versus placebo. RESULTS: Pain improved (RR = 1.25)."
    article = Article("span", "Drug trial", abstract, publication_types=("Randomized Controlled Trial",))
    extraction = extract_clinical(article)
    assert article.abstract == abstract
    assert extraction.interventions[0].normalized_name == "drug"
    assert extraction.population.description == "80 patients with condition were randomized"
    ranked = RankedArticle(article, assess_article(article, NOW, "drug condition"), assess_candidate(article, build_clinical_target("drug efficacy in condition", intervention="drug", condition="condition", query_intents=("efficacy",)), NOW))
    record = build_snapshot("drug condition", "drug condition", NOW, ranked=[ranked])["articles"][0]
    assert record["clinical_relevance"]["requested_intervention_role"] == "primary_intervention"
    assert record["structured_clinical_extraction"]["population"]["provenance"][0]["supporting_span"] in abstract


def test_b4_2_rules_do_not_embed_benchmark_identifiers():
    production_paths = (
        Path("app/models/relevance.py"),
        Path("app/services/clinical_extraction.py"),
        Path("app/services/persistence.py"),
        Path("app/services/relevance.py"),
        Path("app/services/study_design.py"),
    )
    source = "\n".join(path.read_text(encoding="utf-8") for path in production_paths).casefold()
    forbidden = [
        *(record["source_pmid"] for record in _records()),
        "b4_2_multi_topic", "gold_labels.jsonl", "sources.jsonl",
        "acyclovir_herpes_zoster", "losartan_hypertension",
        "acyclovir efficacy and safety in herpes zoster",
        "losartan efficacy and safety in hypertension",
    ]
    assert not [value for value in forbidden if value.casefold() in source]


def test_b4_2_known_false_positive_patterns_abstain_or_use_supported_spans():
    articles = _articles()
    assert extract_clinical(articles["29746903"]).population.description == "One hundred and seventy-four patients were enrolled"
    assert extract_clinical(articles["15181487"]).population.description == "55 patients participated"
    for pmid in ("38520982", "16013891", "38811010"):
        assert extract_clinical(articles[pmid]).comparator.status == "not_reported"
    assert extract_clinical(articles["40342468"]).population.status == "not_reported"
    assert extract_clinical(articles["39273644"]).population.status == "not_reported"
    assert not extract_clinical(articles["16013891"]).safety_findings
    assert [item.name for item in extract_clinical(articles["37535772"]).outcomes] == ["acute pain", "adverse events"]
    assert [item.effect_value for item in extract_clinical(articles["37535772"]).outcomes] == ["OR = 0.25", "OR 4.31"]
    source_text = articles["18422441"].abstract
    assert all(
        provenance.supporting_span in source_text
        for item in extract_clinical(articles["18422441"]).interventions
        for provenance in item.provenance
    )
    target = build_clinical_target(
        "acyclovir efficacy and safety in herpes zoster",
        intervention="acyclovir",
        condition="herpes zoster",
        query_intents=("efficacy", "safety"),
    )
    relevance = assess_candidate(articles["18422441"], target, NOW)
    assert relevance.requested_intervention_role == "pharmacokinetic_reference"
    assert relevance.relevance_class == "contextual"
    proposed = assess_article(articles["37259374"], NOW, "acyclovir herpes zoster").study_assessment
    assert proposed.design_family == "protocol"
    assert proposed.result_status == "not_reported"
    losartan_protocol = assess_article(articles["31907056"], NOW, "losartan hypertension").study_assessment
    assert losartan_protocol.design_family == "protocol"
    assert losartan_protocol.result_status == "not_reported"
    assert assess_article(articles["40858452"], NOW, "losartan hypertension").study_assessment.design_family == "prospective_cohort"


def test_generic_hygiene_rules_preserve_close_positive_clinical_evidence():
    article = Article(
        "close-population",
        "Trial of candesartan for heart failure",
        "Secondary endpoints were the proportion of patients with edema. Eighty adults were enrolled and randomized. "
        "Adverse events were assessed. A Grade 1 adverse event of rash occurred in three participants.",
        publication_types=("Randomized Controlled Trial",),
    )
    clinical = extract_clinical(article)
    assert clinical.population.description == "Eighty adults were enrolled"
    assert [item.event_name for item in clinical.safety_findings] == ["A Grade 1 adverse event of rash occurred in three participants."]
    adherence = Article(
        "close-protocol",
        "Completed randomized trial of metformin",
        "Participants were randomized to metformin versus placebo. Two participants discontinued because of protocol deviation. Results improved.",
        publication_types=("Randomized Controlled Trial",),
    )
    study = assess_article(adherence, NOW, "metformin diabetes").study_assessment
    assert study.design_family == "randomized_controlled_trial"
    assert study.result_status == "reported"
    prospective = Article(
        "close-observational",
        "Prospective observational study of diuretics",
        "This prospective, multicenter, observational study enrolled adults with edema.",
        publication_types=("Observational Study",),
    )
    assert assess_article(prospective, NOW, "diuretics edema").study_assessment.design_family == "prospective_cohort"
