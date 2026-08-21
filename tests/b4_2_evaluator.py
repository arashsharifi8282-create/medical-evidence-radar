"""Deterministic offline evaluator for the frozen Phase B4.2 benchmark."""
from __future__ import annotations

import html
import json
import re
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path

from app.models.article import AbstractSection, Article
from app.services.clinical_extraction import extract_clinical
from app.services.evidence import assess_article
from app.services.persistence import build_html_report, build_markdown_report, build_snapshot
from app.services.relevance import (
    assess_candidate,
    assess_candidates,
    build_clinical_target,
    rank_and_select_candidates,
    ranking_components,
    ranking_sort_key_from_components,
)
from app.services.study_design import assess_study_design

ROOT = Path(__file__).parent / "fixtures" / "b4_2_multi_topic"
LIVE_REGRESSION_RECORDS = Path(__file__).parent / "fixtures" / "b4_2_live_regressions_v1" / "records.jsonl"
NOW = datetime(2026, 8, 21)
FIELDS = (
    "population", "intervention", "comparator", "sample_size",
    "treatment_duration", "follow_up", "outcome", "effect", "safety",
)
ABSTENTION_STATUSES = {
    "not_reported", "not_extractable", "not_safely_extractable", "ambiguous",
    "not_applicable", "planned_not_observed", "unclear",
}
MALFORMED_PATTERNS = (
    r"(?i)^\s*or\s*=\s*18\s*$", r"(?i)^\s*or\s+2\s*$", r"13,;\s*93,;\s*03,;\s*95,",
    r"(?i)patients\s*\(13\b", r"(?i)patients with antivirals monotherapy and 0\b",
    r"(?i)^a and emesis, which occurred",
)


def normalize(value):
    """Apply only transparent Unicode, whitespace, case, and punctuation normalization."""
    if value is None:
        return None
    if isinstance(value, list):
        return [normalize(item) for item in value]
    text = unicodedata.normalize("NFKC", str(value)).casefold()
    text = re.sub(r"[‐‑‒–—]", "-", text)
    return re.sub(r"\s+", " ", text).strip()


def load_jsonl(name: str) -> list[dict]:
    return [json.loads(line) for line in (ROOT / name).read_text(encoding="utf-8").splitlines() if line]


def article_from_source(row: dict) -> Article:
    return Article(
        row["pmid"], row["title"], row["abstract"],
        publication_types=tuple(row["publication_types"]),
        keywords=tuple(row["keywords"]),
        abstract_sections=tuple(AbstractSection(item.get("label", ""), item.get("text", "")) for item in row["abstract_sections"]),
    )


def target_for(topic: str):
    if topic == "acyclovir_herpes_zoster":
        return build_clinical_target(
            "acyclovir efficacy and safety in herpes zoster", intervention="acyclovir",
            condition="herpes zoster", query_intents=("efficacy", "safety"),
        )
    return build_clinical_target(
        "losartan efficacy and safety in hypertension", intervention="losartan",
        condition="hypertension", query_intents=("efficacy", "safety"),
    )


def _provenance(items) -> list[dict]:
    result = []
    for item in items:
        for provenance in getattr(item, "provenance", ()):
            result.append({
                "source_field": provenance.source_section,
                "supporting_span": provenance.supporting_span,
                "rule_id": provenance.rule_id,
                "rule_version": "b4.2",
            })
    return result


def predict(source: dict) -> dict:
    article = article_from_source(source)
    clinical = extract_clinical(article)
    study = assess_study_design(article)
    relevance = assess_candidate(article, target_for(source["topic"]), NOW)
    interventions = [item for item in clinical.interventions if item.status == "reported"]
    outcomes = list(clinical.outcomes)
    safety = list(clinical.safety_findings)
    study_provenance = [
        {"source_field": span.field, "supporting_span": span.text, "rule_id": span.rule_id, "rule_version": study.rule_version}
        for span in study.supporting_spans
    ]

    def field(status, value, provenance):
        return {"status": status, "value": value, "provenance": provenance}

    fields = {
        "population": field(clinical.population.status, clinical.population.description, _provenance([clinical.population])),
        "intervention": field("reported" if interventions else "not_reported", [item.source_text for item in interventions], _provenance(interventions)),
        "comparator": field(clinical.comparator.status, clinical.comparator.source_text, _provenance([clinical.comparator])),
        "sample_size": field(study.sample_size_status, study.sample_size, [p for p in study_provenance if p["rule_id"].startswith("SAMPLE_")]),
        "treatment_duration": field("reported" if clinical.treatment_duration else "not_reported", clinical.treatment_duration, []),
        "follow_up": field("reported" if clinical.follow_up else "not_reported", clinical.follow_up, [p for p in study_provenance if p["rule_id"] == "FOLLOW_UP_EXPLICIT"]),
        "outcome": field("reported" if outcomes else "not_reported", [item.name for item in outcomes], _provenance(outcomes)),
        "effect": field("reported" if outcomes else "not_reported", [item.effect_value for item in outcomes], _provenance(outcomes)),
        "safety": field("reported" if safety else "not_reported", [item.event_name for item in safety], _provenance(safety)),
    }
    if clinical.treatment_duration:
        fields["treatment_duration"]["provenance"] = [{
            "source_field": "abstract", "supporting_span": clinical.treatment_duration,
            "rule_id": "TREATMENT_DURATION_EXPLICIT", "rule_version": study.rule_version,
        }]
    return {
        "pmid": article.pmid,
        "topic": source["topic"],
        "split": source["split"],
        "relevance": {
            "class": relevance.relevance_class,
            "requested_intervention_role": relevance.requested_intervention_role,
            "requested_condition_support": bool(relevance.condition_signals),
            "b2_decision": relevance.decision,
            "supporting_span": relevance.role_supporting_span,
        },
        "study": {
            "design": study.design_family,
            "completion_status": study.result_status,
            "needs_review": study.needs_review,
            "limitation_codes": list(study.limitation_codes),
            "provenance": study_provenance,
        },
        "fields": fields,
    }


def _source_text(source: dict) -> str:
    return "\n".join((source["title"], source["abstract"], *(item.get("text", "") for item in source["abstract_sections"])))


def _provenance_ok(actual: dict, source: dict) -> bool:
    if actual["status"] in ABSTENTION_STATUSES:
        return not actual["value"]
    provenance = actual["provenance"]
    if not provenance:
        return False
    source_text = _source_text(source)
    return all(
        item.get("supporting_span") and item["supporting_span"] in source_text
        and item.get("source_field") and item.get("rule_id") and item.get("rule_version")
        for item in provenance
    )


def _malformed(actual: dict) -> bool:
    values = actual["value"] if isinstance(actual["value"], list) else [actual["value"]]
    for value in (str(item) for item in values if item is not None):
        if any(re.search(pattern, value) for pattern in MALFORMED_PATTERNS):
            return True
        if value.count("(") != value.count(")") or value.count("[") != value.count("]"):
            return True
        if not re.search(r"[A-Za-z]", value) and not re.fullmatch(r"\d+(?:\.\d+)?", value):
            return True
        if re.fullmatch(r"(?i)\s*(?:and|or|versus|vs\.?)\s*", value):
            return True
    return bool(actual["value"]) != (actual["status"] not in ABSTENTION_STATUSES)


def _field_match(actual: dict, gold: dict) -> tuple[bool, bool]:
    status_ok = actual["status"] in gold["acceptable_statuses"]
    if actual["status"] in ABSTENTION_STATUSES:
        return status_ok and actual["value"] in (None, []), False
    accepted = True
    actual_value = normalize(actual["value"])
    values_ok = any(actual_value == normalize(value) for value in gold["acceptable_values"])
    return status_ok and values_ok, accepted


def _supplemental_field_match(actual: dict, expected: dict) -> tuple[bool, bool]:
    """Apply a newer separately checksummed adjudication for one affected field."""
    if expected["status"] == "not_reported":
        return actual["status"] in ABSTENTION_STATUSES and actual["value"] in (None, []), False
    if actual["status"] != expected["status"]:
        return False, actual["status"] not in ABSTENTION_STATUSES
    actual_value = normalize(actual["value"])
    if "value" in expected:
        return actual_value == normalize(expected["value"]), True
    return all(normalize(fragment) in actual_value for fragment in expected.get("contains", ())), True


def _integrity(sources: list[dict]) -> dict:
    counts = Counter()
    details = {}
    for topic in sorted({row["topic"] for row in sources}):
        topic_sources = [row for row in sources if row["topic"] == topic]
        articles = tuple(article_from_source(row) for row in topic_sources)
        target = target_for(topic)
        candidates = assess_candidates(articles, target, NOW)
        selected, audit, fully_ranked = rank_and_select_candidates(candidates, NOW, topic, report_limit=10)
        snapshot = build_snapshot(topic, topic, NOW, ranked=selected, candidates=tuple(audit), clinical_target=target)
        markdown = build_markdown_report(topic, NOW, ranked=selected)
        rendered_html = build_html_report(topic, NOW, ranked=selected)
        selected_ids = [item.article.pmid for item in selected]
        represented = snapshot["represented_article_pmids"]
        if selected_ids != represented:
            counts["selected_disappearance"] += 1
        placements = [
            record["report_placement"]["section"] for record in snapshot["articles"]
            if record["pmid"] in selected_ids
        ]
        if len(placements) != len(selected_ids) or len(set(selected_ids)) != len(selected_ids):
            counts["duplicate_placement"] += 1
        markdown_ids = set(re.findall(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)", markdown))
        html_ids = set(re.findall(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)", rendered_html))
        expected_linked_ids = {item.article.pmid for item in selected if item.article.pubmed_url}
        if markdown_ids != expected_linked_ids or html_ids != expected_linked_ids:
            counts["renderer_disagreement"] += 1
        reconstructed = sorted(fully_ranked, key=lambda item: ranking_sort_key_from_components(ranking_components(item)))
        if [item.article.pmid for item in reconstructed] != [item.article.pmid for item in fully_ranked]:
            counts["ranking_reconstruction_failure"] += 1
        if any(html.escape(item.article.title) not in rendered_html for item in selected):
            counts["html_escaping_failure"] += 1
        if any(item.clinical_relevance.relevance_class == "irrelevant" for item in selected[:10]):
            counts["irrelevant_in_key_evidence"] += 1
        if any(
            item.assessment.study_assessment.design_family == "protocol"
            and item.assessment.study_assessment.result_status == "reported"
            for item in selected
        ):
            counts["protocol_as_results"] += 1
        details[topic] = {"selected_pmids": selected_ids, "represented_pmids": represented}
    for key in (
        "selected_disappearance", "duplicate_placement", "renderer_disagreement",
        "ranking_reconstruction_failure", "html_escaping_failure",
        "irrelevant_in_key_evidence", "protocol_as_results",
    ):
        counts.setdefault(key, 0)
    return {"counts": dict(sorted(counts.items())), "topics": details}


def evaluate(filters: dict[str, str] | None = None) -> dict:
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    sources = load_jsonl("sources.jsonl")
    labels = load_jsonl("gold_labels.jsonl")
    gold_by_id = {row["pmid"]: row for row in labels}
    supplemental = {
        row["pmid"]: row["expected"]
        for row in (json.loads(line) for line in LIVE_REGRESSION_RECORDS.read_text(encoding="utf-8").splitlines() if line)
    }
    selected_sources = [
        row for row in sources
        if not filters or all(row.get(key) == value for key, value in filters.items())
    ]
    predictions = [predict(row) for row in selected_sources]
    field_stats = {
        field: dict(applicable=0, accepted=0, correct=0, incorrect=0, abstained=0, correct_abstentions=0, unsupported=0, malformed=0, provenance_failures=0, failed=[])
        for field in FIELDS
    }
    relevance = dict(total=0, class_correct=0, role_correct=0, condition_correct=0, inclusion_correct=0, direct_expected=0, direct_correct=0)
    study_stats = dict(total=0, design_correct=0, status_correct=0, needs_review_correct=0, false_conflicts=0)
    for source, actual in zip(selected_sources, predictions):
        gold = gold_by_id[source["pmid"]]
        relevance["total"] += 1
        relevance["class_correct"] += actual["relevance"]["class"] == gold["relevance"]["class"]
        relevance["role_correct"] += actual["relevance"]["requested_intervention_role"] == gold["relevance"]["requested_intervention_role"]
        relevance["condition_correct"] += actual["relevance"]["requested_condition_support"] == gold["relevance"]["requested_condition_support"]
        relevance["inclusion_correct"] += actual["relevance"]["b2_decision"] == gold["relevance"]["b2_decision"]
        if gold["relevance"]["class"] == "direct":
            relevance["direct_expected"] += 1
            relevance["direct_correct"] += actual["relevance"]["class"] == "direct"
        study_stats["total"] += 1
        study_stats["design_correct"] += actual["study"]["design"] == gold["study"]["design"]
        study_stats["status_correct"] += actual["study"]["completion_status"] == gold["study"]["completion_status"]
        study_stats["needs_review_correct"] += actual["study"]["needs_review"] == gold["study"]["needs_review"]
        study_stats["false_conflicts"] += "conflicting_design_signals" in actual["study"]["limitation_codes"] and "conflicting_design_signals" not in gold["study"]["limitation_codes"]
        for field in FIELDS:
            stats = field_stats[field]
            expected = gold["fields"][field]
            observed = actual["fields"][field]
            if expected["scored"]:
                stats["applicable"] += 1
            expected_override = supplemental.get(source["pmid"], {}).get(field)
            correct, accepted = (
                _supplemental_field_match(observed, expected_override)
                if expected_override else _field_match(observed, expected)
            )
            if field == "population" and accepted and observed["status"] == "reported":
                actual_population = re.sub(r"\s+(?:were\s+)?randomi[sz]ed$", "", normalize(observed["value"]))
                expected_populations = [
                    re.sub(r"\s+(?:were\s+)?randomi[sz]ed$", "", normalize(value))
                    for value in expected["acceptable_values"] if value is not None
                ]
                correct = correct or actual_population in expected_populations
            provenance_ok = _provenance_ok(observed, source)
            malformed = _malformed(observed)
            stats["accepted"] += accepted
            stats["abstained"] += not accepted
            valid = correct and provenance_ok and not malformed
            stats["correct"] += accepted and valid
            stats["correct_abstentions"] += (not accepted) and valid
            stats["incorrect"] += not valid
            stats["unsupported"] += accepted and (not correct or not provenance_ok)
            stats["malformed"] += malformed
            stats["provenance_failures"] += not provenance_ok
            if not (correct and provenance_ok and not malformed):
                stats["failed"].append({
                    "pmid": source["pmid"], "field": field,
                    "expected_status": expected["acceptable_statuses"],
                    "expected_value": expected["acceptable_values"],
                    "actual_status": observed["status"], "actual_value": observed["value"],
                    "provenance_ok": provenance_ok, "malformed": malformed,
                })
    for stats in field_stats.values():
        stats["precision"] = stats["correct"] / stats["accepted"] if stats["accepted"] else 1.0
        stats["coverage"] = stats["correct"] / stats["applicable"] if stats["applicable"] else 1.0
    total = relevance["total"]
    relevance.update({
        "class_accuracy": relevance["class_correct"] / total if total else 1.0,
        "role_accuracy": relevance["role_correct"] / total if total else 1.0,
        "condition_accuracy": relevance["condition_correct"] / total if total else 1.0,
        "inclusion_accuracy": relevance["inclusion_correct"] / total if total else 1.0,
        "direct_precision": relevance["direct_correct"] / relevance["direct_expected"] if relevance["direct_expected"] else 1.0,
    })
    study_stats.update({
        "design_accuracy": study_stats["design_correct"] / total if total else 1.0,
        "status_accuracy": study_stats["status_correct"] / total if total else 1.0,
        "needs_review_accuracy": study_stats["needs_review_correct"] / total if total else 1.0,
    })
    integrity = _integrity(selected_sources) if not filters else None
    critical = {
        "malformed": sum(stats["malformed"] for stats in field_stats.values()),
        "unsupported_effect": field_stats["effect"]["unsupported"],
        "unsupported_safety": field_stats["safety"]["unsupported"],
        "provenance_failures": sum(stats["provenance_failures"] for stats in field_stats.values()),
    }
    thresholds = {
        "malformed_zero": critical["malformed"] == 0,
        "unsupported_effect_zero": critical["unsupported_effect"] == 0,
        "unsupported_safety_zero": critical["unsupported_safety"] == 0,
        "sample_size_precision": field_stats["sample_size"]["precision"] == 1.0,
        "follow_up_precision": field_stats["follow_up"]["precision"] == 1.0,
        "effect_precision": field_stats["effect"]["precision"] == 1.0,
        "comparator_precision": field_stats["comparator"]["precision"] >= .95,
        "population_precision": field_stats["population"]["precision"] >= .95,
        "intervention_precision": field_stats["intervention"]["precision"] >= .95,
        "role_accuracy": relevance["role_accuracy"] >= .95,
        "study_design_accuracy": study_stats["design_accuracy"] >= .95,
    }
    if integrity:
        thresholds.update({key: value == 0 for key, value in integrity["counts"].items()})
    return {
        "benchmark_version": manifest["benchmark_name"],
        "expected_label_version": manifest["expected_label_version"],
        "record_count": len(predictions),
        "counts": {
            "development": sum(row["split"] == "development" for row in selected_sources),
            "holdout": sum(row["split"] == "holdout" for row in selected_sources),
            "topics": dict(sorted(Counter(row["topic"] for row in selected_sources).items())),
            "designs": dict(sorted(Counter(item["study"]["design"] for item in predictions).items())),
        },
        "relevance": relevance,
        "study": study_stats,
        "fields": field_stats,
        "critical": critical,
        "integrity": integrity,
        "thresholds": thresholds,
        "passed": all(thresholds.values()),
    }
