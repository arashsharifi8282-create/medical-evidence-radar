"""Offline deterministic tests for the B2.2A relevance benchmark evaluator.

These tests exercise the standalone evaluator in scripts/evaluate_relevance_benchmark.py
using small local fixtures. No network requests are made.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import math
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "relevance_benchmark_small"
ARTICLES = FIXTURES / "articles.jsonl"
DRAFT_LABELS = FIXTURES / "draft_labels.jsonl"
ADJUDICATED_LABELS = FIXTURES / "adjudicated_labels.jsonl"

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "evaluate_relevance_benchmark.py"
_spec = importlib.util.spec_from_file_location("evaluate_relevance_benchmark", _SCRIPT)
evaluator = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(evaluator)


def load(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def base_label(**overrides):
    label = {
        "schema_version": "1.0",
        "benchmark_id": "relevance_b2_2a",
        "topic_id": "alpha",
        "pmid": "1001",
        "query": "drugA for condX",
        "target_interventions": ["drugA"],
        "intervention_logic": "OR",
        "target_conditions": ["condX"],
        "gold_relevance_class": "direct",
        "matched_interventions": ["drugA"],
        "matched_conditions": ["condX"],
        "article_focus": "target",
        "coherence_status": "coherent",
        "reason_codes": ["DIRECT_TARGET_FOCUS"],
        "human_or_preclinical": "human",
        "within_class_priority": "not_assessed",
        "reviewer": "test_reviewer",
        "second_reviewer": None,
        "adjudication_notes": "test",
        "label_status": "draft",
        "source_snapshot_sha256": "a" * 64,
    }
    label.update(overrides)
    return label


def base_article(**overrides):
    article = {
        "topic_id": "alpha",
        "retrieval_rank": 1,
        "retrieval_timestamp": "2026-08-01T00:00:00Z",
        "source_snapshot_sha256": "a" * 64,
        "article": {
            "pmid": "1001",
            "title": "DrugA for condX trial",
            "abstract": "A randomized trial of drugA for condX.",
            "authors": ["Smith JA"],
            "journal": "Test Journal",
            "publication_date": "2026-01-01",
            "publication_date_raw": "2026 Jan",
            "publication_types": ["Journal Article"],
            "doi": "10.1000/1001",
            "pubmed_url": "https://pubmed.ncbi.nlm.nih.gov/1001/",
        },
        "prediction": {
            "current_b2_class": "direct",
            "matched_interventions": ["drugA"],
            "provenance": "test",
            "ranking_score": 90,
            "visible_in_default_output": True,
            "visible_section": "key_evidence",
        },
    }
    if "pmid" in overrides:
        article["article"]["pmid"] = overrides["pmid"]
    article.update(overrides)
    return article


def test_schema_validation_rejects_missing_required_fields():
    articles = [base_article()]
    labels = [base_label()]
    del labels[0]["reason_codes"]
    with pytest.raises(ValueError, match="invalid schema"):
        evaluator.evaluate(articles, labels)


def test_controlled_value_rejection_invalid_label_status():
    articles = [base_article()]
    labels = [base_label(label_status="bogus")]
    with pytest.raises(ValueError, match="invalid controlled value"):
        evaluator.evaluate(articles, labels)


def test_controlled_value_rejection_invalid_gold_class():
    articles = [base_article()]
    labels = [base_label(gold_relevance_class="maybe")]
    with pytest.raises(ValueError, match="invalid controlled value"):
        evaluator.evaluate(articles, labels)


def test_controlled_value_rejection_invalid_reason_code():
    articles = [base_article()]
    labels = [base_label(reason_codes=["NOT_A_REAL_CODE"])]
    with pytest.raises(ValueError, match="invalid controlled reason code"):
        evaluator.evaluate(articles, labels)


def test_needs_review_requires_null_gold_class():
    articles = [base_article()]
    labels = [base_label(label_status="needs_review", gold_relevance_class="direct")]
    with pytest.raises(ValueError, match="needs_review requires null"):
        evaluator.evaluate(articles, labels)


def test_duplicate_unit_rejection():
    articles = [base_article(), base_article()]
    labels = [base_label(), base_label()]
    with pytest.raises(ValueError, match="duplicate"):
        evaluator.evaluate(articles, labels)


def test_same_pmid_across_different_topics_allowed():
    articles = [
        base_article(),
        base_article(topic_id="beta", source_snapshot_sha256="b" * 64),
    ]
    labels = [
        base_label(),
        base_label(topic_id="beta", pmid="1001", source_snapshot_sha256="b" * 64),
    ]
    result = evaluator.evaluate(articles, labels)
    assert result["records_evaluated"] == 2


def test_metric_arithmetic_confusion_matrix_and_per_class():
    articles = [
        base_article(),
        base_article(pmid="1002", prediction={"current_b2_class": "direct", "matched_interventions": ["drugA"], "provenance": "test", "ranking_score": 80, "visible_in_default_output": True, "visible_section": "key_evidence"}),
        base_article(pmid="1003", prediction={"current_b2_class": "irrelevant", "matched_interventions": [], "provenance": "test", "ranking_score": 30, "visible_in_default_output": False, "visible_section": "unknown"}),
    ]
    labels = [
        base_label(),
        base_label(pmid="1002", gold_relevance_class="contextual", reason_codes=["BACKGROUND_OR_INCIDENTAL_INTERVENTION_MENTION"]),
        base_label(pmid="1003", gold_relevance_class="irrelevant", reason_codes=["MISSING_INTERVENTION"]),
    ]
    result = evaluator.evaluate(articles, labels)
    cm = result["confusion_matrix"]
    assert cm["direct"]["direct"] == 1
    assert cm["contextual"]["direct"] == 1
    assert cm["irrelevant"]["irrelevant"] == 1
    assert result["per_class"]["direct"]["precision"] == 0.5
    assert result["per_class"]["direct"]["recall"] == 1.0
    assert result["per_class"]["direct"]["f1"] == pytest.approx(2 / 3)
    assert result["per_class"]["irrelevant"]["precision"] == 1.0
    assert result["per_class"]["irrelevant"]["recall"] == 1.0
    assert result["per_class"]["irrelevant"]["f1"] == 1.0


def test_macro_vs_pooled_direct_precision_at_10():
    articles = load(ARTICLES)
    labels = load(DRAFT_LABELS)
    result = evaluator.evaluate(articles, labels)
    # alpha: 2 direct predicted, 1 direct gold -> P@10 = 0.5
    # beta: 1 direct predicted, 1 direct gold -> P@10 = 1.0
    assert result["direct_precision_at_10_by_topic"]["alpha"] == 0.5
    assert result["direct_precision_at_10_by_topic"]["beta"] == 1.0
    assert result["macro_direct_precision_at_10"] == 0.75
    # pooled: (1 direct gold among alpha's 2 predicted direct + 1 among beta's 1) / 3
    assert result["pooled_direct_precision_at_10"] == pytest.approx(2 / 3)


def test_zero_denominator_returns_none():
    articles = [base_article(prediction={"current_b2_class": "irrelevant", "matched_interventions": [], "provenance": "test", "ranking_score": 10, "visible_in_default_output": False, "visible_section": "unknown"})]
    labels = [base_label(gold_relevance_class="irrelevant", reason_codes=["MISSING_INTERVENTION"])]
    result = evaluator.evaluate(articles, labels)
    assert result["per_class"]["direct"]["precision"] is None
    assert result["per_class"]["direct"]["recall"] is None
    assert result["per_class"]["direct"]["f1"] is None
    assert result["direct_precision_at_10_by_topic"]["alpha"] is None
    assert result["macro_direct_precision_at_10"] is None
    assert result["pooled_direct_precision_at_10"] is None


def test_checksum_mismatch_rejected():
    articles = [base_article()]
    labels = [base_label(source_snapshot_sha256="b" * 64)]
    with pytest.raises(ValueError, match="checksum mismatch"):
        evaluator.evaluate(articles, labels)


def test_label_without_source_article_rejected():
    articles = [base_article()]
    labels = [base_label(pmid="9999")]
    with pytest.raises(ValueError, match="label without source article"):
        evaluator.evaluate(articles, labels)


def test_audit_invariants_present():
    articles = load(ARTICLES)
    labels = load(DRAFT_LABELS)
    result = evaluator.evaluate(articles, labels)
    audit = result["audit"]
    assert audit["labels"] == 6
    assert audit["draft"] == 6
    assert audit["needs_review"] == 0
    assert audit["adjudicated"] == 0
    assert "unique (topic_id, PMID)" in audit["invariants"]


def test_official_metrics_refused_without_adjudicated_labels():
    articles = load(ARTICLES)
    labels = load(DRAFT_LABELS)
    with pytest.raises(ValueError, match="official metrics require"):
        evaluator.evaluate(articles, labels, official=True)


def test_official_metrics_use_only_adjudicated_labels():
    articles = load(ARTICLES)
    labels = load(ADJUDICATED_LABELS)
    result = evaluator.evaluate(articles, labels, official=True)
    assert result["result_kind"] == "official"
    assert result["provisional"]["official_relevance_baseline"] is True
    assert result["provisional"]["b2_quality_gate_passed"] is False
    assert result["records_evaluated"] == 2


def test_provisional_diagnostic_prominent_labeling():
    articles = load(ARTICLES)
    labels = load(DRAFT_LABELS)
    result = evaluator.evaluate(articles, labels)
    assert result["result_kind"] == "PROVISIONAL_DIAGNOSTIC_NOT_OFFICIAL_BASELINE"
    assert result["provisional"]["provisional_diagnostic"] is True
    assert result["provisional"]["official_relevance_baseline"] is False
    assert result["provisional"]["b2_quality_gate_passed"] is False
    assert result["provisional"]["human_adjudication_required"] is True
    md = evaluator.render_markdown(result)
    assert "PROVISIONAL DIAGNOSTIC" in md
    assert "NOT AN OFFICIAL RELEVANCE BASELINE" in md
    assert "No B2 quality gate has passed" in md
    assert "Human adjudication is still required" in md


def test_deterministic_repeated_output():
    articles = load(ARTICLES)
    labels = load(DRAFT_LABELS)
    first = evaluator.evaluate(articles, labels)
    second = evaluator.evaluate(articles, labels)
    assert first == second
    assert evaluator.render_markdown(first) == evaluator.render_markdown(second)


def test_evaluator_never_mutates_inputs():
    articles = load(ARTICLES)
    labels = load(DRAFT_LABELS)
    articles_before = copy.deepcopy(articles)
    labels_before = copy.deepcopy(labels)
    evaluator.evaluate(articles, labels)
    assert articles == articles_before
    assert labels == labels_before


def test_needs_review_count_and_rate():
    articles = load(ARTICLES)
    labels = load(DRAFT_LABELS)
    # Convert the alpha/1002 draft label into a needs_review label.
    for label in labels:
        if label["topic_id"] == "alpha" and label["pmid"] == "1002":
            label["label_status"] = "needs_review"
            label["gold_relevance_class"] = None
            label["article_focus"] = "unknown"
            label["coherence_status"] = "unknown"
            label["reason_codes"] = ["AMBIGUOUS_FROM_AVAILABLE_METADATA"]
    result = evaluator.evaluate(articles, labels)
    assert result["needs_review"]["count"] == 1
    assert result["needs_review"]["rate"] == pytest.approx(1 / 6)


def test_irrelevant_leakage_and_key_evidence_count():
    articles = load(ARTICLES)
    labels = load(DRAFT_LABELS)
    # Make the alpha irrelevant article visible in default output and key evidence.
    for a in articles:
        if a["topic_id"] == "alpha" and a["article"]["pmid"] == "1003":
            a["prediction"]["visible_in_default_output"] = True
            a["prediction"]["visible_section"] = "key_evidence"
    result = evaluator.evaluate(articles, labels)
    assert result["gold_irrelevant_leakage_visible"] == 1
    assert result["gold_irrelevant_key_evidence"] == 1


def test_incidental_background_to_direct_error_rate():
    articles = load(ARTICLES)
    labels = load(DRAFT_LABELS)
    # alpha 1002 is gold contextual with BACKGROUND reason; its prediction is direct.
    result = evaluator.evaluate(articles, labels)
    assert result["incidental_background_to_direct_error_rate"] == 1.0


def test_multi_intervention_exact_set_accuracy():
    articles = [
        base_article(
            pmid="3001",
            prediction={"current_b2_class": "direct", "matched_interventions": ["drugA", "drugB"], "provenance": "test", "ranking_score": 90, "visible_in_default_output": True, "visible_section": "key_evidence"},
        )
    ]
    labels = [
        base_label(
            pmid="3001",
            target_interventions=["drugA", "drugB"],
            matched_interventions=["drugA", "drugB"],
            reason_codes=["DIRECT_TARGET_FOCUS"],
        )
    ]
    result = evaluator.evaluate(articles, labels)
    assert result["multi_intervention_exact_set_accuracy"] == 1.0


def test_matched_intervention_micro_metrics():
    articles = load(ARTICLES)
    labels = load(DRAFT_LABELS)
    result = evaluator.evaluate(articles, labels)
    mm = result["matched_intervention_micro"]
    # gold matched sets: alpha 1001 [drugA], 1002 [drugA], 1003 []; beta 2001 [drugB], 2002 [drugB], 2003 []
    # predicted matched sets: alpha 1001 [drugA], 1002 [drugA], 1003 []; beta 2001 [drugB], 2002 [drugB], 2003 []
    assert mm["precision"] == 1.0
    assert mm["recall"] == 1.0
    assert mm["f1"] == 1.0


def test_pairwise_ordering_accuracy():
    articles = load(ARTICLES)
    labels = load(DRAFT_LABELS)
    result = evaluator.evaluate(articles, labels)
    # alpha: 1001 direct rank 1, 1002 contextual rank 2, 1003 irrelevant rank 3 -> correct
    # beta: 2001 direct rank 1, 2002 contextual rank 2, 2003 irrelevant rank 3 -> correct
    assert result["pairwise_ordering_accuracy"] == 1.0


def test_direct_ndcg_at_10():
    articles = load(ARTICLES)
    labels = load(DRAFT_LABELS)
    result = evaluator.evaluate(articles, labels)
    # alpha ranked [1001 direct, 1002 contextual, 1003 irrelevant]
    # gains [1,0,0]; dcg = 1/log2(2) = 1.0; idcg = 1.0; ndcg = 1.0
    assert result["ranking_ndcg_at_10_within_direct"]["alpha"] == 1.0
    # beta ranked [2001 direct, 2002 contextual, 2003 irrelevant]
    assert result["ranking_ndcg_at_10_within_direct"]["beta"] == 1.0


def test_class_level_false_positive_rate():
    articles = [
        base_article(prediction={"current_b2_class": "class_level", "matched_interventions": ["drugA"], "provenance": "test", "ranking_score": 70, "visible_in_default_output": True, "visible_section": "important_updates"}),
        base_article(pmid="1002", prediction={"current_b2_class": "direct", "matched_interventions": ["drugA"], "provenance": "test", "ranking_score": 90, "visible_in_default_output": True, "visible_section": "key_evidence"}),
    ]
    labels = [
        base_label(gold_relevance_class="direct", reason_codes=["DIRECT_TARGET_FOCUS"]),
        base_label(pmid="1002", gold_relevance_class="direct", reason_codes=["DIRECT_TARGET_FOCUS"]),
    ]
    result = evaluator.evaluate(articles, labels)
    # 1 false positive class_level out of 2 non-class gold records
    assert result["class_level_false_positive_rate"] == 0.5


def test_direct_recall():
    articles = load(ARTICLES)
    labels = load(DRAFT_LABELS)
    result = evaluator.evaluate(articles, labels)
    # gold direct: alpha 1001, beta 2001 (2 total); predicted direct among those: both
    assert result["direct_recall"] == 1.0


def test_cli_returns_nonzero_on_invalid_input(tmp_path):
    bad_articles = tmp_path / "bad_articles.jsonl"
    bad_articles.write_text("not json\n", encoding="utf-8")
    out = tmp_path / "out.json"
    rc = evaluator.main(["--articles", str(bad_articles), "--labels", str(DRAFT_LABELS), "--output", str(out)])
    assert rc == 2


def test_cli_writes_json_and_markdown(tmp_path):
    out = tmp_path / "out.json"
    out_md = tmp_path / "out.md"
    rc = evaluator.main(
        [
            "--articles", str(ARTICLES),
            "--labels", str(DRAFT_LABELS),
            "--output", str(out),
            "--output-md", str(out_md),
        ]
    )
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["result_kind"] == "PROVISIONAL_DIAGNOSTIC_NOT_OFFICIAL_BASELINE"
    md = out_md.read_text(encoding="utf-8")
    assert "PROVISIONAL DIAGNOSTIC" in md