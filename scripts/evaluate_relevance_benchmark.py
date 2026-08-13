"""Offline deterministic B2.2A relevance benchmark evaluator; never mutates inputs.

Produces deterministic JSON and Markdown reports. Official metrics are computed
only from adjudicated labels. Without adjudicated labels the evaluator refuses
official quality-gate reporting and emits a prominently-labeled provisional
diagnostic instead. Invalid schema, duplicate units, checksum mismatches, and
broken invariants return a non-zero exit code.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

CLASSES = ("direct", "class_level", "contextual", "irrelevant")
REASONS = {
    "CROSS_FIELD_COOCCURRENCE_WITHOUT_COHERENCE",
    "BACKGROUND_OR_INCIDENTAL_INTERVENTION_MENTION",
    "COMPARATOR_OR_STANDARD_CARE_ONLY",
    "AUTHOR_KEYWORD_ONLY_INTERVENTION",
    "BROAD_MULTI_INTERVENTION_REVIEW",
    "OTHER_INTERVENTION_PRIMARY_FOCUS",
    "PRECLINICAL_HUMAN_MISMATCH",
    "NON_STRUCTURAL_RXCLASS_RELATIONSHIP",
    "TARGET_SET_COLLAPSED_TO_SINGLE_INTERVENTION",
    "STRUCTURED_ABSTRACT_PROVENANCE_LOST",
    "UNRESOLVED_TARGET_NORMALIZATION_NOT_BLOCKING",
    "MISSING_INTERVENTION",
    "MISSING_CONDITION",
    "VERIFIED_CLASS_FOCUS",
    "DIRECT_TARGET_FOCUS",
    "AMBIGUOUS_FROM_AVAILABLE_METADATA",
}
REQ = {
    "schema_version",
    "benchmark_id",
    "topic_id",
    "pmid",
    "query",
    "target_interventions",
    "intervention_logic",
    "target_conditions",
    "gold_relevance_class",
    "matched_interventions",
    "matched_conditions",
    "article_focus",
    "coherence_status",
    "reason_codes",
    "human_or_preclinical",
    "within_class_priority",
    "reviewer",
    "second_reviewer",
    "adjudication_notes",
    "label_status",
    "source_snapshot_sha256",
}

PROVISIONAL_BANNER = (
    "PROVISIONAL DIAGNOSTIC - NOT AN OFFICIAL RELEVANCE BASELINE\n"
    "No B2 quality gate has passed. Human adjudication is still required."
)


def load(path):
    """Load a JSONL file into a list of dicts. Raises ValueError on bad JSON."""
    try:
        return [
            json.loads(line)
            for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except Exception as exc:  # noqa: BLE001 - surface any parse failure
        raise ValueError(f"invalid JSONL: {path}: {exc}") from exc


def div(a, b):
    """Explicit zero-denominator behavior: return None instead of dividing by zero."""
    return None if not b else a / b


def f1(precision, recall):
    """Harmonic mean; returns None when either component is unavailable or zero-sum."""
    if precision is None or recall is None or not precision + recall:
        return None
    return 2 * precision * recall / (precision + recall)


def validate(labels, amap):
    """Validate schema, controlled values, uniqueness, source binding, and checksums."""
    seen = set()
    for item in labels:
        if REQ - item.keys():
            raise ValueError("invalid schema: missing required fields")
        if item["label_status"] not in {"draft", "needs_review", "adjudicated"}:
            raise ValueError("invalid controlled value: label_status")
        if item["gold_relevance_class"] not in {*CLASSES, None}:
            raise ValueError("invalid controlled value: gold_relevance_class")
        if not set(item["reason_codes"]) <= REASONS:
            raise ValueError("invalid controlled reason code")
        if item["label_status"] == "needs_review" and item["gold_relevance_class"] is not None:
            raise ValueError("needs_review requires null gold_relevance_class")
        key = (item["topic_id"], item["pmid"])
        if key in seen:
            raise ValueError("duplicate (topic_id, PMID)")
        seen.add(key)
        if key not in amap:
            raise ValueError("label without source article")
        if item["source_snapshot_sha256"] != amap[key]["source_snapshot_sha256"]:
            raise ValueError("checksum mismatch")


def _provisional_block(official, has_adjudicated):
    return {
        "provisional_diagnostic": not official,
        "official_relevance_baseline": official,
        "b2_quality_gate_passed": False,
        "human_adjudication_required": not has_adjudicated,
    }


def evaluate(articles, labels, official=False):
    """Compute all B2.2A metrics. Never mutates inputs."""
    amap = {(a["topic_id"], a["article"]["pmid"]): a for a in articles}
    if len(amap) != len(articles):
        raise ValueError("duplicate (topic_id, PMID)")
    validate(labels, amap)

    chosen = [
        item for item in labels
        if item["label_status"] == "adjudicated" and item["gold_relevance_class"]
    ]
    if official and not chosen:
        raise ValueError("official metrics require valid adjudicated labels")
    kind = "official" if official else "PROVISIONAL_DIAGNOSTIC_NOT_OFFICIAL_BASELINE"
    if not chosen:
        chosen = [
            item for item in labels
            if item["label_status"] == "draft" and item["gold_relevance_class"]
        ]

    matrix = {gold: {pred: 0 for pred in CLASSES} for gold in CLASSES}
    usable = []
    for item in chosen:
        article = amap[(item["topic_id"], item["pmid"])]
        pred = article["prediction"]["current_b2_class"]
        if pred in CLASSES:
            matrix[item["gold_relevance_class"]][pred] += 1
            usable.append((item, article, pred))

    per_class = {}
    for cls in CLASSES:
        tp = matrix[cls][cls]
        fp = sum(matrix[gold][cls] for gold in CLASSES if gold != cls)
        fn = sum(matrix[cls][pred] for pred in CLASSES if pred != cls)
        precision, recall = div(tp, tp + fp), div(tp, tp + fn)
        per_class[cls] = {
            "precision": precision,
            "recall": recall,
            "f1": f1(precision, recall),
            "support": sum(matrix[cls].values()),
        }

    total = len(usable)
    micro = div(sum(matrix[cls][cls] for cls in CLASSES), total)

    groups = defaultdict(list)
    for item, article, pred in usable:
        groups[item["topic_id"]].append((item, article, pred))

    p10 = {}
    ndcg = {}
    pairs = []
    for topic, items in groups.items():
        ranked = sorted(
            items, key=lambda z: (z[1].get("retrieval_rank", 999999), z[0]["pmid"])
        )[:10]
        pred_direct = [z for z in ranked if z[2] == "direct"]
        p10[topic] = div(
            sum(z[0]["gold_relevance_class"] == "direct" for z in pred_direct),
            len(pred_direct),
        )
        gains = [1 if z[0]["gold_relevance_class"] == "direct" else 0 for z in ranked]
        dcg = sum(gain / math.log2(i + 2) for i, gain in enumerate(gains))
        ideal = sorted(gains, reverse=True)
        idcg = sum(gain / math.log2(i + 2) for i, gain in enumerate(ideal))
        ndcg[topic] = div(dcg, idcg)
        for i, left in enumerate(items):
            for right in items[i + 1:]:
                left_direct = left[0]["gold_relevance_class"] == "direct"
                right_direct = right[0]["gold_relevance_class"] == "direct"
                if left_direct != right_direct:
                    pairs.append(
                        (left[1].get("retrieval_rank", 999999) < right[1].get("retrieval_rank", 999999))
                        == left_direct
                    )

    tp_matched = sum(
        len(set(item["matched_interventions"]) & set(article["prediction"].get("matched_interventions", [])))
        for item, article, _ in usable
    )
    pred_total = sum(
        len(article["prediction"].get("matched_interventions", []))
        for _, article, _ in usable
    )
    gold_total = sum(len(item["matched_interventions"]) for item, _, _ in usable)

    leakage = [
        (item, article)
        for item, article, pred in usable
        if item["gold_relevance_class"] == "irrelevant"
        and article["prediction"].get("visible_in_default_output")
    ]
    incidental = [
        (item, article)
        for item, article, _ in usable
        if "BACKGROUND_OR_INCIDENTAL_INTERVENTION_MENTION" in item["reason_codes"]
    ]

    macro = {
        metric: div(
            sum(per_class[cls][metric] for cls in CLASSES if per_class[cls][metric] is not None),
            sum(per_class[cls][metric] is not None for cls in CLASSES),
        )
        for metric in ("precision", "recall", "f1")
    }

    pooled_numerator = sum(
        sum(
            z[0]["gold_relevance_class"] == "direct"
            for z in sorted(v, key=lambda z: z[1].get("retrieval_rank", 999999))[:10]
            if z[2] == "direct"
        )
        for v in groups.values()
    )
    pooled_denominator = sum(
        sum(z[2] == "direct" for z in sorted(v, key=lambda z: z[1].get("retrieval_rank", 999999))[:10])
        for v in groups.values()
    )

    needs_review_count = sum(item["label_status"] == "needs_review" for item in labels)

    result = {
        "result_kind": kind,
        "provisional": _provisional_block(official, bool(chosen) and official),
        "records_evaluated": total,
        "confusion_matrix": matrix,
        "per_class": per_class,
        "macro": macro,
        "micro": {"precision": micro, "recall": micro, "f1": micro},
        "direct_recall": per_class["direct"]["recall"],
        "direct_precision_at_10_by_topic": p10,
        "macro_direct_precision_at_10": div(
            sum(v for v in p10.values() if v is not None),
            sum(v is not None for v in p10.values()),
        ),
        "pooled_direct_precision_at_10": div(pooled_numerator, pooled_denominator),
        "gold_irrelevant_leakage_visible": len(leakage),
        "gold_irrelevant_key_evidence": sum(
            article["prediction"].get("visible_section") == "key_evidence"
            for _, article in leakage
        ),
        "class_level_false_positive_rate": div(
            sum(matrix[gold]["class_level"] for gold in CLASSES if gold != "class_level"),
            total - sum(matrix["class_level"].values()),
        ),
        "incidental_background_to_direct_error_rate": div(
            sum(article["prediction"]["current_b2_class"] == "direct" for _, article in incidental),
            len(incidental),
        ),
        "multi_intervention_exact_set_accuracy": div(
            sum(
                set(item["matched_interventions"]) == set(article["prediction"].get("matched_interventions", []))
                for item, article, _ in usable
                if len(item["target_interventions"]) > 1
            ),
            sum(len(item["target_interventions"]) > 1 for item, _, _ in usable),
        ),
        "matched_intervention_micro": {
            "precision": div(tp_matched, pred_total),
            "recall": div(tp_matched, gold_total),
            "f1": f1(div(tp_matched, pred_total), div(tp_matched, gold_total)),
        },
        "needs_review": {
            "count": needs_review_count,
            "rate": div(needs_review_count, len(labels)),
        },
        "ranking_ndcg_at_10_within_direct": ndcg,
        "pairwise_ordering_accuracy": div(sum(pairs), len(pairs)),
        "audit": {
            "labels": len(labels),
            "draft": sum(item["label_status"] == "draft" for item in labels),
            "needs_review": needs_review_count,
            "adjudicated": sum(item["label_status"] == "adjudicated" for item in labels),
            "invariants": "unique (topic_id, PMID), source checksum, controlled values",
        },
    }
    return result


def _fmt(value):
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def render_markdown(result):
    """Render a deterministic Markdown report from an evaluate() result."""
    lines = []
    lines.append("# B2.2A relevance benchmark report")
    lines.append("")
    if result["result_kind"] != "official":
        lines.append("> **" + PROVISIONAL_BANNER + "**")
        lines.append("")
    lines.append(f"- Result kind: `{result['result_kind']}`")
    lines.append(f"- Records evaluated: {result['records_evaluated']}")
    lines.append(f"- Provisional diagnostic: {result['provisional']['provisional_diagnostic']}")
    lines.append(f"- Official relevance baseline: {result['provisional']['official_relevance_baseline']}")
    lines.append(f"- B2 quality gate passed: {result['provisional']['b2_quality_gate_passed']}")
    lines.append(f"- Human adjudication required: {result['provisional']['human_adjudication_required']}")
    lines.append("")

    lines.append("## Confusion matrix (gold rows x predicted columns)")
    lines.append("")
    header = "| gold \\ pred | " + " | ".join(CLASSES) + " |"
    lines.append(header)
    lines.append("|" + "---|" * (len(CLASSES) + 1))
    for gold in CLASSES:
        row = "| " + gold + " | " + " | ".join(str(result["confusion_matrix"][gold][pred]) for pred in CLASSES) + " |"
        lines.append(row)
    lines.append("")

    lines.append("## Per-class metrics")
    lines.append("")
    lines.append("| class | precision | recall | F1 | support |")
    lines.append("|---|---|---|---|---|")
    for cls in CLASSES:
        pc = result["per_class"][cls]
        lines.append(
            f"| {cls} | {_fmt(pc['precision'])} | {_fmt(pc['recall'])} | {_fmt(pc['f1'])} | {pc['support']} |"
        )
    lines.append("")

    lines.append("## Macro and micro metrics")
    lines.append("")
    lines.append(f"- Macro precision: {_fmt(result['macro']['precision'])}")
    lines.append(f"- Macro recall: {_fmt(result['macro']['recall'])}")
    lines.append(f"- Macro F1: {_fmt(result['macro']['f1'])}")
    lines.append(f"- Micro precision/recall/F1: {_fmt(result['micro']['precision'])}")
    lines.append("")

    lines.append("## Direct Precision@10")
    lines.append("")
    for topic, value in result["direct_precision_at_10_by_topic"].items():
        lines.append(f"- {topic}: {_fmt(value)}")
    lines.append(f"- Macro direct P@10: {_fmt(result['macro_direct_precision_at_10'])}")
    lines.append(f"- Pooled direct P@10: {_fmt(result['pooled_direct_precision_at_10'])}")
    lines.append(f"- Direct recall: {_fmt(result['direct_recall'])}")
    lines.append("")

    lines.append("## Leakage and error analysis")
    lines.append("")
    lines.append(f"- Gold-irrelevant leakage visible in default output: {result['gold_irrelevant_leakage_visible']}")
    lines.append(f"- Gold-irrelevant count in Key evidence: {result['gold_irrelevant_key_evidence']}")
    lines.append(f"- Class-level false-positive rate: {_fmt(result['class_level_false_positive_rate'])}")
    lines.append(f"- Incidental/background-to-direct error rate: {_fmt(result['incidental_background_to_direct_error_rate'])}")
    lines.append("")

    lines.append("## Intervention matching")
    lines.append("")
    lines.append(f"- Multi-intervention exact-set accuracy: {_fmt(result['multi_intervention_exact_set_accuracy'])}")
    mm = result["matched_intervention_micro"]
    lines.append(f"- Matched-set micro precision: {_fmt(mm['precision'])}")
    lines.append(f"- Matched-set micro recall: {_fmt(mm['recall'])}")
    lines.append(f"- Matched-set micro F1: {_fmt(mm['f1'])}")
    lines.append("")

    lines.append("## Ranking quality")
    lines.append("")
    lines.append(f"- Needs-review count: {result['needs_review']['count']}")
    lines.append(f"- Needs-review rate: {_fmt(result['needs_review']['rate'])}")
    lines.append(f"- Pairwise ordering accuracy: {_fmt(result['pairwise_ordering_accuracy'])}")
    lines.append("- Direct nDCG@10 by topic:")
    for topic, value in result["ranking_ndcg_at_10_within_direct"].items():
        lines.append(f"  - {topic}: {_fmt(value)}")
    lines.append("")

    lines.append("## Audit")
    lines.append("")
    audit = result["audit"]
    lines.append(f"- Labels: {audit['labels']}")
    lines.append(f"- Draft: {audit['draft']}")
    lines.append(f"- Needs review: {audit['needs_review']}")
    lines.append(f"- Adjudicated: {audit['adjudicated']}")
    lines.append(f"- Invariants: {audit['invariants']}")
    lines.append("")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--articles", required=True)
    parser.add_argument("--labels", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--output-md", default=None)
    parser.add_argument("--official", action="store_true")
    args = parser.parse_args(argv)

    try:
        result = evaluate(load(args.articles), load(args.labels), args.official)
    except ValueError as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 2

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    md_path = Path(args.output_md) if args.output_md else output.with_suffix(".md")
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_markdown(result), encoding="utf-8")

    print(result["result_kind"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())