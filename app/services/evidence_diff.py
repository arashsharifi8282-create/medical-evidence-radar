"""Phase B6: deterministic comparison of two persisted evidence snapshots.

Pure and offline: :func:`compare_snapshots` takes two already-loaded
snapshot dicts plus an audit-only timestamp and returns a canonical
comparison result. File loading, artefact saving, and the module CLI are
kept separate from the semantic diff. No network, no LLM, no clinical
interpretation.
"""

from __future__ import annotations

import hashlib
import html
import json
from datetime import datetime
from pathlib import Path

COMPARISON_SCHEMA_VERSION = "b6/1.0"
ARTICLE_IDENTITY_POLICY_VERSION = "1.0"
SNAPSHOT_COMPAT_POLICY_VERSION = "1.0"
COMPARABILITY_POLICY_VERSION = "1.0"
COMPARISON_PRIORITY_POLICY_VERSION = "1.0"
SUPPORTED_SNAPSHOT_VERSIONS = ("b5",)

RELEVANCE_FIELDS = ("relevance_class", "decision", "relevance_score")
STUDY_DESIGN_FIELDS = ("design_family", "design_subtype")
STUDY_RESULT_FIELDS = ("result_status", "evidence_tier")
INTEGRITY_FIELDS = ("status", "record_role", "final_decision",
                    "report_eligible")
PLACEMENT_FIELDS = ("section", "visible", "display_mode")
AUDIT_ONLY_KEYS = {"assessed_at", "fetched_at"}
ABSTENTION_VALUES = {"not_reported", "not_extractable", "not_applicable",
                     "unclear", "unknown", "unspecified"}

CATEGORY_PRIORITY = {
    "integrity": 1,
    "membership": 2,
    "relevance": 3,
    "study": 4,
    "extraction": 5,
    "review": 6,
    "ranking": 7,
    "placement": 7,
    "comparability": 8,
}


class ComparisonError(Exception):
    """Structured deterministic comparison failure."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=str)


def _digest(value) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _semantic_snapshot_id(snapshot: dict) -> str:
    """Digest B6-comparable snapshot content, excluding audit-only variation.

    Raw snapshot digests remain in audit metadata for source provenance.  This
    digest includes exactly the B6-compared article state, normalizing the
    candidate-set order and extraction lists that B6 compares as multisets.
    """
    articles = [_semantic_article(record) for record in snapshot["articles"]]
    material = {
        "schema_version": snapshot.get("schema_version"),
        "topic": _available_text(snapshot, "topic"),
        "query": snapshot.get("query"),
        "articles": sorted(articles, key=_canonical),
    }
    return _digest(material)


def _semantic_block(record: dict, block: str, fields: tuple[str, ...]) -> dict:
    """Project one persisted block onto exactly the state B6 compares."""
    present, value = _block_value(record, block)
    state = _block_state(record, block)
    if state != "present":
        return {"state": state}
    if not isinstance(value, dict):
        return {"state": state, "value": value}
    return {"state": state,
            "fields": {field: value.get(field) for field in fields}}


def _semantic_extraction(value):
    """Normalize extraction containers using B6's ordered/unordered rules."""
    if isinstance(value, dict):
        return {key: _semantic_extraction(item) for key, item in sorted(value.items())
                if key not in AUDIT_ONLY_KEYS and key != "pmid"}
    if isinstance(value, list):
        if all(isinstance(item, dict) for item in value):
            return sorted((_semantic_extraction(item) for item in value), key=_canonical)
        if all(not isinstance(item, (dict, list)) for item in value):
            return sorted(value, key=_canonical)
        return [_semantic_extraction(item) for item in value]
    return value


def _semantic_article(record: dict) -> dict:
    """Project one candidate to B6 semantic comparison state only."""
    extraction_present, extraction_value = _block_value(
        record, "structured_clinical_extraction")
    extraction_state = _block_state(record, "structured_clinical_extraction")
    return {
        "pmid": _canonical_pmid(record),
        # B6 exposes a title only for membership additions/removals.
        "title": record.get("title", ""),
        "clinical_relevance": _semantic_block(
            record, "clinical_relevance", RELEVANCE_FIELDS + ("needs_review",)),
        "assessment": {"state": _block_state(record, "assessment"),
                       "study_assessment": _semantic_block(
                           record, "assessment.study_assessment",
                           STUDY_DESIGN_FIELDS + STUDY_RESULT_FIELDS +
                           ("needs_review",))},
        "publication_integrity": _semantic_block(
            record, "publication_integrity", INTEGRITY_FIELDS + ("needs_review",)),
        "structured_clinical_extraction": (
            {"state": extraction_state,
             "value": _semantic_extraction(extraction_value)}
            if extraction_present and extraction_state == "present"
            else {"state": extraction_state}),
        "final_evidence_rank": _semantic_block(
            record, "final_evidence_rank", ()),
        "report_placement": _semantic_block(
            record, "report_placement", PLACEMENT_FIELDS),
    }


def _canonical_pmid(record: dict) -> str:
    pmid = record.get("pmid", "")
    return pmid.strip() if isinstance(pmid, str) else ""


def _index(snapshot: dict, role: str):
    """Return (by_pmid, unmatched) or raise on duplicates/malformed."""
    articles = snapshot.get("articles")
    if not isinstance(articles, list):
        raise ComparisonError("malformed_snapshot",
                              f"{role} snapshot has no 'articles' list")
    by_pmid: dict[str, dict] = {}
    unmatched: list[dict] = []
    for position, record in enumerate(articles):
        if not isinstance(record, dict):
            raise ComparisonError(
                "malformed_snapshot",
                f"{role} snapshot article at index {position} is not an object")
        pmid = _canonical_pmid(record)
        if not pmid:
            # An array position is not a stable identity.  Retain a digest for
            # audit while avoiding any temptation to pair records by order.
            unmatched.append({"snapshot": role,
                              "record_digest": _digest(record)[:16]})
            continue
        if pmid in by_pmid:
            raise ComparisonError(
                "duplicate_pmid",
                f"{role} snapshot contains duplicate PMID {pmid}")
        by_pmid[pmid] = record
    return by_pmid, unmatched


def _available_text(snapshot: dict, key: str) -> str | None:
    """Return a valid non-empty scope string; otherwise ``None``.

    Topics are identifiers for the stored evidence collection, not prose to
    fuzzy-match.  Exact comparison deliberately avoids inferring that two
    differently named collections are longitudinally comparable.
    """
    value = snapshot.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _comparability_status(baseline: dict, target: dict) -> tuple[dict, list[dict]]:
    """Validate/describe collection scope before article-state comparison."""
    baseline_topic = _available_text(baseline, "topic")
    target_topic = _available_text(target, "topic")
    baseline_query = baseline.get("query")
    target_query = target.get("query")
    base_query_available = isinstance(baseline_query, str)
    target_query_available = isinstance(target_query, str)
    status = {
        "policy_version": COMPARABILITY_POLICY_VERSION,
        "scope": "same_topic",
        "baseline_topic_present": baseline_topic is not None,
        "target_topic_present": target_topic is not None,
        "query_changed": False,
        "baseline_query_present": base_query_available,
        "target_query_present": target_query_available,
    }
    changes: list[dict] = []
    if baseline_topic is not None and target_topic is not None:
        if baseline_topic != target_topic:
            raise ComparisonError(
                "incomparable_snapshots",
                "snapshot topics differ and cannot be compared: "
                f"baseline={baseline_topic!r}; target={target_topic!r}")
        if base_query_available and target_query_available:
            status["query_changed"] = baseline_query != target_query
            if status["query_changed"]:
                changes.append(_change(
                    "comparability", "query_changed", "", "query",
                    {"present": True, "value": baseline_query},
                    {"present": True, "value": target_query},
                    CATEGORY_PRIORITY["comparability"],
                    "stored search query changed between snapshots", {}))
        else:
            status["query_status"] = "unavailable"
        return status, changes

    status["scope"] = ("topic_unavailable" if baseline_topic is None
                       and target_topic is None
                       else "topic_partially_unavailable")
    changes.append(_change(
        "comparability", "scope_unverifiable", "", "topic",
        {"present": "topic" in baseline, "value": baseline.get("topic")},
        {"present": "topic" in target, "value": target.get("topic")},
        CATEGORY_PRIORITY["comparability"],
        "snapshot topic scope could not be verified", {
            "baseline_topic_present": baseline_topic is not None,
            "target_topic_present": target_topic is not None,
        }))
    return status, changes


def _block_state(record: dict, block: str) -> str:
    """Classify B5 persisted-state availability without conflating null/absent."""
    value = record
    for key in block.split("."):
        if not isinstance(value, dict) or key not in value:
            return "absent"
        value = value[key]
    if value is None:
        return "null"
    if block == "final_evidence_rank":
        return "present"
    return "present" if isinstance(value, dict) else "invalid"


def _block_value(record: dict, block: str) -> tuple[bool, object]:
    """Return an exact persisted block value with absence distinct from null."""
    value = record
    for key in block.split("."):
        if not isinstance(value, dict) or key not in value:
            return False, None
        value = value[key]
    return True, value


def _block_availability_changes(pmid: str, old: dict, new: dict) -> list[dict]:
    """Expose non-comparable B5 block transitions as factual audit changes.

    B5 deliberately uses explicit null/omission for excluded candidates.  A
    B6 comparison must not invent detailed study/extraction/ranking changes
    across that boundary, but it must not silently discard the transition.
    """
    changes: list[dict] = []
    for block in ("clinical_relevance", "assessment",
                  "assessment.study_assessment", "publication_integrity",
                  "structured_clinical_extraction", "final_evidence_rank",
                  "report_placement"):
        parent = block.rpartition(".")[0]
        if parent and _block_state(old, parent) != _block_state(new, parent):
            # A changed parent availability already describes this transition;
            # do not duplicate it for a child B5 block.
            continue
        old_state, new_state = _block_state(old, block), _block_state(new, block)
        if old_state == new_state:
            continue
        old_present = old_state == "present"
        new_present = new_state == "present"
        if not old_present and new_present:
            change_type = "block_became_comparable"
        elif old_present and not new_present:
            change_type = "block_became_not_comparable"
        else:
            change_type = "block_state_changed"
        old_present, old_value = _block_value(old, block)
        new_present, new_value = _block_value(new, block)
        changes.append(_change(
            "comparability", change_type, pmid, block,
            {"present": old_present, "value": old_value},
            {"present": new_present, "value": new_value},
            CATEGORY_PRIORITY["comparability"],
            f"stored block availability changed for article {pmid}: "
            f"{old_state} to {new_state}",
            {"block": block, "baseline_state": old_state,
             "target_state": new_state}))
    return changes


def _check_versions(baseline: dict, target: dict) -> None:
    bad = [role for role, snap in (("baseline", baseline), ("target", target))
           if not isinstance(snap.get("schema_version"), str)
           or snap.get("schema_version") not in SUPPORTED_SNAPSHOT_VERSIONS]
    if bad:
        raise ComparisonError(
            "unsupported_schema_version",
            f"unsupported schema_version for: {', '.join(bad)}; "
            f"supported: {', '.join(SUPPORTED_SNAPSHOT_VERSIONS)}")


def _study(record: dict) -> dict | None:
    assessment = record.get("assessment")
    if not isinstance(assessment, dict):
        return None
    study = assessment.get("study_assessment")
    return study if isinstance(study, dict) else None


def _review_sources(record: dict) -> dict:
    sources = {}
    relevance = record.get("clinical_relevance")
    sources["relevance"] = (relevance.get("needs_review")
                            if isinstance(relevance, dict) else None)
    study = _study(record)
    sources["study"] = study.get("needs_review") if study else None
    integrity = record.get("publication_integrity")
    sources["integrity"] = (integrity.get("needs_review")
                            if isinstance(integrity, dict) else None)
    extraction = record.get("structured_clinical_extraction")
    sources["extraction"] = (extraction.get("needs_review")
                             if isinstance(extraction, dict) else None)
    return sources


def _is_abstention(present: bool, value) -> bool:
    if not present or value is None or value == "":
        return True
    if isinstance(value, str) and value in ABSTENTION_VALUES:
        return True
    if isinstance(value, list) and not value:
        return True
    return False


def _leaves(value, path: str):
    """Yield (leaf_path, present, leaf_value) for recursive extraction diff."""
    if isinstance(value, dict):
        items = [(key, value[key]) for key in sorted(value)
                 if key not in AUDIT_ONLY_KEYS and key != "pmid"]
        if not items:
            yield path, True, {}
            return
        for key, item in items:
            child = f"{path}.{key}" if path else str(key)
            yield from _leaves(item, child)
    elif isinstance(value, list):
        if all(isinstance(item, dict) for item in value):
            yield path, True, sorted(_canonical(item) for item in value)
        elif not value:
            yield path, True, []
        elif all(not isinstance(item, (dict, list)) for item in value):
            yield path, True, sorted(value, key=lambda v: _canonical(v))
        else:
            for index, item in enumerate(value):
                yield from _leaves(item, f"{path}[{index}]")
    else:
        yield path, True, value
def _compare_records_a(pmid: str, old: dict, new: dict) -> list[dict]:
    changes: list[dict] = []
    old_rel = old.get("clinical_relevance")
    new_rel = new.get("clinical_relevance")
    if isinstance(old_rel, dict) and isinstance(new_rel, dict):
        differing = [f for f in RELEVANCE_FIELDS
                     if _canonical(old_rel.get(f)) != _canonical(new_rel.get(f))]
        if differing:
            changes.append(_change(
                "relevance", "relevance_changed", pmid, "",
                {"present": True, "value": {f: old_rel.get(f)
                                            for f in differing}},
                {"present": True, "value": {f: new_rel.get(f)
                                            for f in differing}},
                CATEGORY_PRIORITY["relevance"],
                f"relevance changed from {old_rel.get('relevance_class')} "
                f"to {new_rel.get('relevance_class')} for article {pmid}",
                {"differing": sorted(differing)}))
    old_study, new_study = _study(old), _study(new)
    if isinstance(old_study, dict) and isinstance(new_study, dict):
        design = [f for f in STUDY_DESIGN_FIELDS
                  if _canonical(old_study.get(f)) != _canonical(new_study.get(f))]
        if design:
            changes.append(_change(
                "study", "study_design_changed", pmid, "",
                {"present": True,
                 "value": {f: old_study.get(f) for f in design}},
                {"present": True,
                 "value": {f: new_study.get(f) for f in design}},
                CATEGORY_PRIORITY["study"],
                f"study design changed from "
                f"{old_study.get('design_subtype')} to "
                f"{new_study.get('design_subtype')} for article {pmid}",
                {"differing": sorted(design)}))
        res = [f for f in STUDY_RESULT_FIELDS
               if _canonical(old_study.get(f)) != _canonical(new_study.get(f))]
        if res:
            changes.append(_change(
                "study", "study_result_changed", pmid, "",
                {"present": True, "value": {f: old_study.get(f) for f in res}},
                {"present": True, "value": {f: new_study.get(f) for f in res}},
                CATEGORY_PRIORITY["study"],
                f"study result status changed for article {pmid}",
                {"differing": sorted(res)}))
    return changes
def _compare_records_b(pmid: str, old: dict, new: dict) -> list[dict]:
    changes: list[dict] = []
    old_sources, new_sources = _review_sources(old), _review_sources(new)
    old_any = any(v is True for v in old_sources.values())
    new_any = any(v is True for v in new_sources.values())
    source_changed = old_sources != new_sources
    if old_any != new_any or source_changed:
        changes.append(_change(
            "review", "review_required_changed", pmid, "",
            {"present": True, "value": old_any},
            {"present": True, "value": new_any},
            CATEGORY_PRIORITY["review"],
            f"review requirement changed from {old_any} to {new_any} "
            f"for article {pmid}",
            {"sources": {k: [old_sources[k], new_sources[k]]
                         for k in sorted(old_sources)}}))
    old_int, new_int = old.get("publication_integrity"), new.get(
        "publication_integrity")
    if isinstance(old_int, dict) and isinstance(new_int, dict):
        differing = [f for f in INTEGRITY_FIELDS
                     if _canonical(old_int.get(f)) != _canonical(new_int.get(f))]
        if differing:
            changes.append(_change(
                "integrity", "integrity_changed", pmid, "",
                {"present": True, "value": {f: old_int.get(f)
                                            for f in differing}},
                {"present": True, "value": {f: new_int.get(f)
                                            for f in differing}},
                CATEGORY_PRIORITY["integrity"],
                f"integrity status changed from {old_int.get('status')} "
                f"to {new_int.get('status')} for article {pmid}",
                {"differing": sorted(differing)}))
    return changes
def _extraction_changes(pmid: str, old: dict, new: dict) -> list[dict]:
    changes: list[dict] = []
    old_map = {p: (pr, v) for p, pr, v in _leaves(old, "")}
    new_map = {p: (pr, v) for p, pr, v in _leaves(new, "")}
    for path in sorted(set(old_map) | set(new_map)):
        in_old, in_new = path in old_map, path in new_map
        pob, vob = old_map.get(path, (False, None))
        pnb, vnb = new_map.get(path, (False, None))
        if in_old and in_new and _canonical(vob) == _canonical(vnb):
            continue
        segs = path.split(".")
        prov_only = "provenance" in segs or "warnings" in segs
        if not in_old:
            ctype = "extraction_added"
        elif not in_new:
            ctype = "extraction_removed"
        elif prov_only:
            ctype = "extraction_provenance_only"
        elif _is_abstention(pob, vob) and not _is_abstention(pnb, vnb):
            ctype = "extraction_abstention_to_accepted"
        elif _is_abstention(pnb, vnb) and not _is_abstention(pob, vob):
            ctype = "extraction_accepted_to_abstention"
        else:
            ctype = "extraction_changed"
        before = {"present": in_old, "value": vob}
        after = {"present": in_new, "value": vnb}
        if ctype == "extraction_added":
            desc = f"extraction field {path} was added for article {pmid}"
        elif ctype == "extraction_removed":
            desc = f"extraction field {path} was removed for article {pmid}"
        elif ctype == "extraction_abstention_to_accepted":
            desc = (f"extraction field {path} changed from abstention to "
                    f"an accepted value for article {pmid}")
        elif ctype == "extraction_accepted_to_abstention":
            desc = (f"extraction field {path} changed from an accepted "
                    f"value to abstention for article {pmid}")
        elif ctype == "extraction_provenance_only":
            desc = f"extraction provenance changed at {path} for {pmid}"
        else:
            desc = f"extraction field {path} changed for article {pmid}"
        priority = 7 if prov_only else CATEGORY_PRIORITY["extraction"]
        changes.append(_change("extraction", ctype, pmid, path, before,
                               after, priority, desc, {}))
    return changes


def _compare_records_c(pmid: str, old: dict, new: dict,
                       membership_changed: bool) -> list[dict]:
    changes: list[dict] = []
    old_ext, new_ext = old.get("structured_clinical_extraction"), new.get(
        "structured_clinical_extraction")
    if isinstance(old_ext, dict) and isinstance(new_ext, dict):
        changes.extend(_extraction_changes(pmid, old_ext, new_ext))
    old_rank, new_rank = old.get("final_evidence_rank"), new.get(
        "final_evidence_rank")
    if (old_rank != new_rank and old_rank is not None
            and new_rank is not None):
        changes.append(_change(
            "ranking", "rank_changed", pmid, "",
            {"present": True, "value": old_rank},
            {"present": True, "value": new_rank},
            CATEGORY_PRIORITY["ranking"],
            f"rank changed from {old_rank} to {new_rank} for article {pmid}",
            {"candidate_set_changed": membership_changed}))
    old_place, new_place = old.get("report_placement"), new.get(
        "report_placement")
    if isinstance(old_place, dict) and isinstance(new_place, dict):
        differing = [f for f in PLACEMENT_FIELDS
                     if _canonical(old_place.get(f)) != _canonical(
                         new_place.get(f))]
        if differing:
            became_key = (new_place.get("section") == "key_evidence"
                          and old_place.get("section") != "key_evidence")
            ctype = ("became_key_evidence" if became_key
                     else "placement_changed")
            changes.append(_change(
                "placement", ctype, pmid, "",
                {"present": True, "value": {f: old_place.get(f)
                                            for f in differing}},
                {"present": True, "value": {f: new_place.get(f)
                                            for f in differing}},
                CATEGORY_PRIORITY["placement"],
                f"report placement changed from "
                f"{old_place.get('section')} to {new_place.get('section')} "
                f"for article {pmid}",
                {"differing": sorted(differing)}))
    return changes


def _change(category: str, change_type: str, pmid: str, field_path: str,
            baseline: dict, target: dict, priority: int,
            description: str, detail: dict) -> dict:
    seed = {"category": category, "change_type": change_type, "pmid": pmid,
            "field_path": field_path, "baseline": baseline, "target": target}
    return {"change_id": _digest(seed)[:16], "category": category,
            "change_type": change_type, "pmid": pmid,
            "field_path": field_path, "baseline": baseline,
            "target": target, "priority": priority,
            "description": description, "detail": detail}
def _fmt(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "absent"
    text = _canonical(value)
    return text if len(text) <= 120 else text[:117] + "..."


def compare_snapshots(baseline: dict, target: dict,
                      compared_at: str | None = None) -> dict:
    """Compare two loaded snapshots; pure and deterministic."""
    if not isinstance(baseline, dict) or not isinstance(target, dict):
        raise ComparisonError("malformed_snapshot",
                              "snapshot inputs must be objects")
    for role, snap in (("baseline", baseline), ("target", target)):
        if not isinstance(snap.get("articles"), list):
            raise ComparisonError(
                "malformed_snapshot",
                f"{role} snapshot has no 'articles' list")
    _check_versions(baseline, target)
    comparability, changes = _comparability_status(baseline, target)
    base_by_pmid, base_unmatched = _index(baseline, "baseline")
    target_by_pmid, target_unmatched = _index(target, "target")
    membership_changed = (set(base_by_pmid) != set(target_by_pmid))
    for pmid in sorted(set(target_by_pmid) - set(base_by_pmid)):
        changes.append(_change(
            "membership", "added", pmid, "",
            {"present": False, "value": None},
            {"present": True, "value": target_by_pmid[pmid].get("title", "")},
            CATEGORY_PRIORITY["membership"],
            f"article {pmid} was added to the candidate set", {}))
    for pmid in sorted(set(base_by_pmid) - set(target_by_pmid)):
        changes.append(_change(
            "membership", "removed", pmid, "",
            {"present": True, "value": base_by_pmid[pmid].get("title", "")},
            {"present": False, "value": None},
            CATEGORY_PRIORITY["membership"],
            f"article {pmid} is not in the target candidate set", {}))
    for pmid in sorted(set(base_by_pmid) & set(target_by_pmid)):
        old, new = base_by_pmid[pmid], target_by_pmid[pmid]
        changes.extend(_block_availability_changes(pmid, old, new))
        changes.extend(_compare_records_a(pmid, old, new))
        changes.extend(_compare_records_b(pmid, old, new))
        changes.extend(_compare_records_c(pmid, old, new,
                                          membership_changed))
    changes.sort(key=lambda c: (c["priority"], c["category"],
                                c["change_type"], c["pmid"], c["field_path"]))
    counts = {category: 0 for category in
              ("membership", "relevance", "study", "review", "integrity",
               "extraction", "ranking", "placement", "comparability")}
    for change in changes:
        counts[change["category"]] += 1
    baseline_id = _digest(baseline)
    target_id = _digest(target)
    baseline_semantic_id = _semantic_snapshot_id(baseline)
    target_semantic_id = _semantic_snapshot_id(target)
    comparability["identical_content"] = baseline_id == target_id
    compared = compared_at or datetime.now().isoformat()
    comparison_id = hashlib.sha256(
        f"{baseline_semantic_id}:{target_semantic_id}:{COMPARISON_SCHEMA_VERSION}:"
        f"{ARTICLE_IDENTITY_POLICY_VERSION}:{SNAPSHOT_COMPAT_POLICY_VERSION}:"
        f"{COMPARABILITY_POLICY_VERSION}:"
        f"{COMPARISON_PRIORITY_POLICY_VERSION}".encode("utf-8")).hexdigest()
    unmatched = sorted(base_unmatched + target_unmatched,
                       key=lambda record: (record["snapshot"],
                                           record["record_digest"]))
    occurrences: dict[tuple[str, str], int] = {}
    for record in unmatched:
        key = (record["snapshot"], record["record_digest"])
        occurrences[key] = occurrences.get(key, 0) + 1
        record["occurrence"] = occurrences[key]
    meta = {"comparison_schema_version": COMPARISON_SCHEMA_VERSION,
            "article_identity_policy_version": ARTICLE_IDENTITY_POLICY_VERSION,
            "snapshot_compatibility_policy_version":
                SNAPSHOT_COMPAT_POLICY_VERSION,
            "comparability_policy_version": COMPARABILITY_POLICY_VERSION,
            "comparison_priority_policy_version":
                COMPARISON_PRIORITY_POLICY_VERSION,
            "baseline_snapshot_id": baseline_id,
            "target_snapshot_id": target_id,
            "baseline_semantic_snapshot_id": baseline_semantic_id,
            "target_semantic_snapshot_id": target_semantic_id,
            "baseline_schema_version": baseline.get("schema_version"),
            "target_schema_version": target.get("schema_version"),
            "baseline_topic": baseline.get("topic"),
            "target_topic": target.get("topic"),
            "baseline_query": baseline.get("query"),
            "target_query": target.get("query"),
            "baseline_fetched_at": baseline.get("fetched_at"),
            "target_fetched_at": target.get("fetched_at"),
            "comparability": comparability,
            "comparison_id": comparison_id, "compared_at": compared,
            "counts": counts, "total_changes": len(changes),
            "summary": {"unmatched_count": len(unmatched)},
            "unmatched_records": unmatched}
    return {"meta": meta, "changes": changes}
def load_snapshot_file(path) -> dict:
    """Load one snapshot file or raise a structured ComparisonError."""
    path = Path(path)
    if not path.exists():
        raise ComparisonError("snapshot_not_found",
                              f"snapshot file not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ComparisonError("snapshot_unreadable",
                              f"snapshot file is not readable JSON: {exc}")
    if not isinstance(payload, dict):
        raise ComparisonError("malformed_snapshot",
                              "snapshot file does not contain an object")
    return payload


def canonical_json(result: dict) -> str:
    """Deterministic canonical serialization of a comparison result."""
    return _canonical(result) + "\n"


def render_markdown_comparison(result: dict) -> str:
    """Render the canonical result as Markdown; adds no new facts."""
    meta = result["meta"]
    scope = meta["comparability"]
    safe = lambda value: html.escape(str(value))
    lines = ["# Evidence change report", "",
             f"Baseline snapshot: `{safe(meta['baseline_snapshot_id'])}`",
             f"Target snapshot: `{safe(meta['target_snapshot_id'])}`",
             f"Comparison schema: `{safe(meta['comparison_schema_version'])}`",
             f"Compared at: {safe(meta['compared_at'])}",
             f"Scope: {safe(scope['scope'])}",
             f"Search query changed: {safe(_fmt(scope['query_changed']))}",
             f"Total changes: {meta['total_changes']}", ""]
    if result["changes"]:
        lines.append("## Changes (in review order)")
        lines.append("")
        for change in result["changes"]:
            field = (f" @ {safe(change['field_path'])}"
                     if change["field_path"] else "")
            lines.append(
                f"- **{safe(change['change_type'])}** "
                f"[{safe(change['category'])}/p{change['priority']}] "
                f"PMID {safe(change['pmid'] or 'n/a')}{field}: "
                f"{safe(change['description'])} "
                f"(baseline {safe(_fmt(change['baseline']['value']))} -> "
                f"target {safe(_fmt(change['target']['value']))})")
        lines.append("")
    else:
        lines.append("No changes detected between the two snapshots.")
        lines.append("")
    if meta["unmatched_records"]:
        lines.append(
            f"Note: {meta['summary']['unmatched_count']} record(s) without "
            "a PMID could not be matched and were excluded.")
        lines.append("")
    return "\n".join(lines)
def render_html_comparison(result: dict) -> str:
    """Render the canonical result as standalone HTML; adds no new facts."""
    meta = result["meta"]
    scope = meta["comparability"]
    rows = []
    for change in result["changes"]:
        cells = [html.escape(str(change[k])) for k in
                 ("change_type", "category", "pmid", "field_path",
                  "description")]
        cells.append(html.escape(_fmt(change["baseline"]["value"])))
        cells.append(html.escape(_fmt(change["target"]["value"])))
        rows.append("<tr><td>" + "</td><td>".join(cells) + "</td></tr>")
    if rows:
        body = ("<table><thead><tr><th>Change type</th><th>Category</th>"
                "<th>PMID</th><th>Field</th><th>Description</th>"
                "<th>Baseline</th><th>Target</th></tr></thead><tbody>"
                + "".join(rows) + "</tbody></table>")
    else:
        body = "<p>No changes detected between the two snapshots.</p>"
    unmatched = ""
    if meta["unmatched_records"]:
        unmatched = (f"<p>{meta['summary']['unmatched_count']} record(s) "
                     "without a PMID could not be matched.</p>")
    return ("<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<title>Evidence change report</title>"
            "<style>body{font-family:sans-serif;max-width:70em;margin:auto}"
            "table{border-collapse:collapse}"
            "td,th{border:1px solid #999;padding:4px}</style></head><body>"
            "<h1>Evidence change report</h1>"
            f"<p>Baseline snapshot: {html.escape(meta['baseline_snapshot_id'])}"
            f"<br>Target snapshot: {html.escape(meta['target_snapshot_id'])}"
            "<br>Comparison schema: "
            f"{html.escape(meta['comparison_schema_version'])}"
             f"<br>Scope: {html.escape(scope['scope'])}"
             f"<br>Search query changed: {_fmt(scope['query_changed'])}"
            f"<br>Total changes: {meta['total_changes']}</p>"
            f"{body}{unmatched}</body></html>")


def save_comparison(result: dict, output_dir, stem: str):
    """Persist canonical JSON, Markdown, and HTML for one comparison."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": output_dir / f"{stem}.comparison.json",
        "markdown": output_dir / f"{stem}.comparison.md",
        "html": output_dir / f"{stem}.comparison.html",
    }
    paths["json"].write_text(canonical_json(result), encoding="utf-8")
    paths["markdown"].write_text(render_markdown_comparison(result),
                                 encoding="utf-8")
    paths["html"].write_text(render_html_comparison(result), encoding="utf-8")
    return paths


def main(argv=None) -> None:
    """CLI: compare two explicitly supplied snapshot files (read-only)."""
    import argparse
    import sys
    parser = argparse.ArgumentParser(
        prog="python -m app.services.evidence_diff",
        description="Compare two saved evidence snapshots (read-only).")
    parser.add_argument("baseline", help="Baseline snapshot JSON path.")
    parser.add_argument("target", help="Target snapshot JSON path.")
    parser.add_argument("--out-dir", default="reports/evidence_diff")
    args = parser.parse_args(argv)
    try:
        baseline = load_snapshot_file(args.baseline)
        target = load_snapshot_file(args.target)
        result = compare_snapshots(baseline, target)
    except ComparisonError as exc:
        print(f"comparison failed [{exc.code}]: {exc}", file=sys.stderr)
        raise SystemExit(2)
    stem = f"{Path(args.baseline).stem}_vs_{Path(args.target).stem}"
    paths = save_comparison(result, args.out_dir, stem)
    print(f"changes: {result['meta']['total_changes']}")
    for key, path in paths.items():
        print(f"saved {key}: {path}")


if __name__ == "__main__":
    main()
