"""Offline Phase B6 evidence-change-detection tests.

Pure, deterministic, no network. Snapshots are minimal hand-built ``b5``
dicts exercising one behavior each.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

from app.services import evidence_diff as diff
from app.services.integrity import assess_publication_integrity
from app.services.normalizer import normalize_article, parse_pubmed_articles
from app.services.persistence import build_snapshot
from app.services.relevance import rank_and_select_candidates
from app.models.relevance import AssessedCandidate, ClinicalRelevanceAssessment
from app.models.article import Article


FIXED_COMPARED_AT = "2026-08-28T09:00:00+00:00"


B5_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "b5_publication_integrity"
B5_FIXED_DT = datetime(2026, 8, 27, 9, 0, 0)


def _fixture_articles():
    xml = (B5_FIXTURE_DIR / "records.xml").read_text(encoding="utf-8")
    return [normalize_article(item) for item in parse_pubmed_articles(xml)]


def _relevance_dict(**over):
    base = {
        "relevance_class": "direct",
        "decision": "included_direct",
        "relevance_score": 90,
        "needs_review": False,
    }
    base.update(over)
    return base


def _relevance(pmid, relevance_class="direct"):
    return ClinicalRelevanceAssessment(
        pmid=pmid,
        relevance_class=relevance_class,
        relevance_score=90,
        intervention_signals=(),
        condition_signals=(),
        decision=f"included_{relevance_class}",
        reason="Controlled relevance decision.",
        assessed_at=B5_FIXED_DT,
        query_intents=("efficacy",),
        article_intents=("efficacy",),
        article_focus="target_intervention_primary",
    )


def _study(**over):
    base = {
        "design_family": "randomized_trial",
        "design_subtype": "rct",
        "result_status": "results_reported",
        "evidence_tier": "tier_2",
        "needs_review": False,
    }
    base.update(over)
    return base


def _integrity(**over):
    base = {
        "status": "no_signal",
        "record_role": "primary_article",
        "final_decision": "include",
        "report_eligible": True,
        "needs_review": False,
    }
    base.update(over)
    return base


def _extraction(**over):
    base = {
        "pmid": "0",
        "needs_review": False,
        "population": {"description": "adults", "scope": "human", "status": "reported"},
        "comparator": {"kind": "placebo", "status": "reported"},
    }
    base.update(over)
    return base


def _placement(**over):
    base = {"section": "key_evidence", "visible": True, "display_mode": "primary"}
    base.update(over)
    return base


def _record(pmid, **over):
    record = {
        "pmid": pmid,
        "title": f"Study {pmid}",
        "clinical_relevance": _relevance_dict(),
        "assessment": {"study_assessment": _study()},
        "publication_integrity": _integrity(),
        "structured_clinical_extraction": _extraction(pmid=pmid),
        "final_evidence_rank": 1,
        "report_placement": _placement(),
    }
    for key, value in over.items():
        if value is None and key in record:
            del record[key]
        else:
            record[key] = value
    return record


def _snapshot(records, schema="b5", topic="b6 controlled topic"):
    return {
        "schema_version": schema,
        "topic": topic,
        "query": topic,
        "fetched_at": "2026-08-27T09:00:00+00:00",
        "articles": list(records),
    }


def _compare(baseline_records, target_records, **kwargs):
    return diff.compare_snapshots(
        _snapshot(baseline_records), _snapshot(target_records),
        compared_at=FIXED_COMPARED_AT, **kwargs,
    )


def _by_type(result, change_type):
    return [c for c in result["changes"] if c["change_type"] == change_type]


def test_noop_comparison_has_zero_changes_and_valid_artifacts():
    records = [_record("101"), _record("102")]
    result = _compare(records, [_record("101"), _record("102")])
    assert result["meta"]["total_changes"] == 0
    assert result["changes"] == []
    assert result["meta"]["comparison_schema_version"] == "b6/1.0"
    assert result["meta"]["baseline_snapshot_id"] == result["meta"]["target_snapshot_id"]
    # Canonical JSON round-trips; renderers agree there is nothing to report.
    json.loads(diff.canonical_json(result))
    markdown = diff.render_markdown_comparison(result)
    html = diff.render_html_comparison(result)
    assert "No changes" in markdown
    assert "No changes" in html
    assert result["meta"]["baseline_snapshot_id"] in markdown
    assert result["meta"]["baseline_snapshot_id"] in html
def test_new_candidate_is_reported_as_added():
    result = _compare([_record("101")], [_record("101"), _record("102")])
    added = _by_type(result, "added")
    assert len(added) == 1 and added[0]["pmid"] == "102"
    assert added[0]["category"] == "membership"
    assert result["meta"]["counts"]["membership"] == 1


def test_removed_candidate_language_is_neutral():
    result = _compare([_record("101"), _record("102")], [_record("101")])
    removed = _by_type(result, "removed")
    assert len(removed) == 1 and removed[0]["pmid"] == "102"
    text = removed[0]["description"] + diff.render_markdown_comparison(result)
    for banned in ("retract", "invalid", "deleted", "disproven"):
        assert banned not in text.lower()


def test_relevance_change_reports_before_after():
    target = _record("101", clinical_relevance=_relevance_dict(
        relevance_class="contextual", decision="included_contextual",
        relevance_score=55))
    result = _compare([_record("101")], [target])
    changed = _by_type(result, "relevance_changed")
    assert len(changed) == 1
    assert changed[0]["detail"]["differing"] == [
        "decision", "relevance_class", "relevance_score"]
def test_study_design_and_result_changes_are_distinct():
    design = _record("101", assessment={"study_assessment": _study(
        design_family="observational", design_subtype="cohort")})
    result = _compare([_record("101")], [design])
    assert len(_by_type(result, "study_design_changed")) == 1
    assert _by_type(result, "study_result_changed") == []
    tiered = _record("101", assessment={"study_assessment": _study(
        evidence_tier="tier_3")})
    result2 = _compare([_record("101")], [tiered])
    assert len(_by_type(result2, "study_result_changed")) == 1


def test_review_requirement_change_reports_sources():
    target = _record("101", clinical_relevance=_relevance_dict(
        needs_review=True))
    result = _compare([_record("101")], [target])
    changed = _by_type(result, "review_required_changed")
    assert len(changed) == 1
    assert changed[0]["detail"]["sources"]["relevance"] == [False, True]


def test_integrity_change_covers_retraction_and_eligibility():
    target = _record("101", publication_integrity=_integrity(
        status="retracted", final_decision="excluded_integrity",
        report_eligible=False))
    result = _compare([_record("101")], [target])
    changed = _by_type(result, "integrity_changed")
    assert len(changed) == 1
    assert set(changed[0]["detail"]["differing"]) == {
        "final_decision", "report_eligible", "status"}
    assert changed[0]["priority"] == 1
def test_extraction_added_removed_changed():
    base = _record("101")
    changed_desc = _record("101", structured_clinical_extraction=_extraction(
        pmid="101", population={"description": "children", "scope": "human",
                                "status": "reported"}))
    result = _compare([base], [changed_desc])
    leaves = [c for c in result["changes"] if c["category"] == "extraction"]
    assert [c["change_type"] for c in leaves] == ["extraction_changed"]
    assert leaves[0]["field_path"] == "population.description"


def test_extraction_abstention_transitions_have_own_types():
    to_abs = _record("101", structured_clinical_extraction=_extraction(
        pmid="101", population={"description": "not_reported",
                                "scope": "unclear", "status": "not_reported"}))
    types = {c["change_type"] for c in _compare([_record("101")], [to_abs])[
        "changes"] if c["category"] == "extraction"}
    assert "extraction_accepted_to_abstention" in types
    types2 = {c["change_type"] for c in _compare([to_abs], [_record("101")])[
        "changes"] if c["category"] == "extraction"}
    assert "extraction_abstention_to_accepted" in types2


def test_rank_change_marks_membership_effect_and_placement():
    baseline = [_record("101", final_evidence_rank=1,
                        report_placement=_placement(section="key_evidence")),
                _record("102", final_evidence_rank=2,
                        report_placement=_placement(
                            section="additional_selected_evidence"))]
    target = [_record("101", final_evidence_rank=2,
                      report_placement=_placement(
                          section="additional_selected_evidence")),
              _record("102", final_evidence_rank=1,
                      report_placement=_placement(section="key_evidence"))]
    result = _compare(baseline, target)
    ranks = sorted(_by_type(result, "rank_changed"),
                   key=lambda c: c["pmid"])
    assert [c["pmid"] for c in ranks] == ["101", "102"]
    assert all(c["detail"]["candidate_set_changed"] is False
               for c in ranks)
    keyed = _by_type(result, "became_key_evidence")
    assert [c["pmid"] for c in keyed] == ["102"]
def test_multiple_changes_on_one_entity_are_all_represented():
    target = _record("101",
                     clinical_relevance=_relevance_dict(
                         relevance_class="contextual",
                         decision="included_contextual", relevance_score=55),
                     final_evidence_rank=2)
    result = _compare([_record("101")], [target])
    types = {c["change_type"] for c in result["changes"]}
    assert {"relevance_changed", "rank_changed"} <= types


def test_duplicate_pmid_fails_closed():
    with pytest.raises(diff.ComparisonError) as exc:
        _compare([_record("101"), _record("101")], [_record("101")])
    assert exc.value.code == "duplicate_pmid"
    assert "101" in str(exc.value) and "baseline" in str(exc.value)


def test_missing_pmid_is_unmatched_never_fuzzy_matched():
    ghost = _record("", title="Same Title", final_evidence_rank=1)
    other = _record("", title="Same Title", final_evidence_rank=2)
    result = diff.compare_snapshots(
        _snapshot([_record("101"), ghost]),
        _snapshot([_record("101"), other]),
        compared_at=FIXED_COMPARED_AT)
    assert result["meta"]["total_changes"] == 0
    assert result["meta"]["summary"]["unmatched_count"] == 2
    assert len(result["meta"]["unmatched_records"]) == 2
def test_version_compatibility_matrix():
    good = _record("101")
    assert _compare([good], [good])["meta"]["total_changes"] == 0
    with pytest.raises(diff.ComparisonError) as exc:
        diff.compare_snapshots(_snapshot([good], schema="legacy"),
                               _snapshot([good]),
                               compared_at=FIXED_COMPARED_AT)
    assert exc.value.code == "unsupported_schema_version"
    with pytest.raises(diff.ComparisonError) as exc2:
        diff.compare_snapshots({"no": "articles"}, _snapshot([good]),
                               compared_at=FIXED_COMPARED_AT)
    assert exc2.value.code == "malformed_snapshot"
    with pytest.raises(diff.ComparisonError):
        diff.compare_snapshots(_snapshot([good], schema="b9"),
                               _snapshot([good]),
                               compared_at=FIXED_COMPARED_AT)


def test_determinism_under_reordering_and_repetition():
    baseline = [_record("101"), _record("102")]
    target = [_record("102"), _record("101",
                                        clinical_relevance=_relevance_dict(
        relevance_class="contextual", decision="included_contextual",
        relevance_score=55))]
    first = diff.compare_snapshots(
        _snapshot(baseline), _snapshot(target),
        compared_at=FIXED_COMPARED_AT)
    again = diff.compare_snapshots(
        _snapshot(list(reversed(baseline))), _snapshot(list(reversed(target))),
        compared_at="2099-01-01T00:00:00+00:00")
    assert [c["change_id"] for c in first["changes"]] == [
        c["change_id"] for c in again["changes"]]
    assert [c["change_type"] for c in first["changes"]] == [
        c["change_type"] for c in again["changes"]]


def test_priority_tie_breaking_is_stable():
    baseline = [_record("101"), _record("102")]
    target = [_record("102", final_evidence_rank=1),
              _record("101", final_evidence_rank=2)]
    one = _compare(baseline, target)
    two = _compare(list(reversed(baseline)), list(reversed(target)))
    assert [c["change_id"] for c in one["changes"]] == [
        c["change_id"] for c in two["changes"]]
def test_renderers_are_semantically_equivalent():
    target = _record("101", publication_integrity=_integrity(
        status="corrected_or_updated"))
    result = _compare([_record("101"), _record("102")],
                      [target, _record("103")])
    markdown = diff.render_markdown_comparison(result)
    html = diff.render_html_comparison(result)
    for change in result["changes"]:
        assert change["pmid"] in markdown
        assert change["pmid"] in html
        assert change["change_type"] in markdown
        assert change["change_type"] in html
    assert "b6/1.0" in markdown and "b6/1.0" in html
    assert "<script" not in html.lower()


def test_no_clinical_interpretation_in_descriptions():
    target = _record("101", publication_integrity=_integrity(
        status="retracted", final_decision="excluded_integrity",
        report_eligible=False))
    result = _compare([_record("101")], [target])
    banned = ("stronger", "safer", "confirms", "confidence increas",
              "should now be preferred", "clinically meaningful")
    blob = " ".join(c["description"] for c in result["changes"]).lower()
    blob += diff.render_markdown_comparison(result).lower()
    for phrase in banned:
        assert phrase not in blob


def test_b6_real_b5_snapshots_detect_integrity_and_membership_changes():
    articles = _fixture_articles()
    by_pmid = {item.pmid: item for item in articles}
    baseline_candidates = [
        AssessedCandidate(by_pmid["99000005"], _relevance("99000005"),
                          assess_publication_integrity(by_pmid["99000005"])),
        AssessedCandidate(by_pmid["99000008"], _relevance("99000008"),
                          assess_publication_integrity(by_pmid["99000008"])),
    ]
    target_candidates = [
        AssessedCandidate(by_pmid["99000005"], _relevance("99000005"),
                          assess_publication_integrity(by_pmid["99000005"])),
        AssessedCandidate(by_pmid["99000001"], _relevance("99000001"),
                          assess_publication_integrity(by_pmid["99000001"])),
    ]
    selected_base, audited_base, _ = rank_and_select_candidates(
        baseline_candidates, B5_FIXED_DT, "generic topic", 2)
    selected_target, audited_target, _ = rank_and_select_candidates(
        target_candidates, B5_FIXED_DT, "generic topic", 2)
    baseline = build_snapshot(topic="generic topic", query="generic topic",
                              fetched_at=B5_FIXED_DT, ranked=selected_base,
                              candidates=tuple(audited_base))
    target = build_snapshot(topic="generic topic", query="generic topic",
                            fetched_at=B5_FIXED_DT, ranked=selected_target,
                            candidates=tuple(audited_target))
    result = diff.compare_snapshots(baseline, target,
                                    compared_at=FIXED_COMPARED_AT)
    types = {(c["category"], c["change_type"], c["pmid"])
             for c in result["changes"]}
    assert ("membership", "removed", "99000008") in types
    assert ("membership", "added", "99000001") in types
    assert "99000001" not in {c["pmid"] for c in result["changes"]
                              if c["category"] == "study"}
    markdown = diff.render_markdown_comparison(result)
    html = diff.render_html_comparison(result)
    assert "99000001" in markdown and "99000001" in html
    assert "No changes" not in markdown


def test_load_snapshot_file_errors_are_structured(tmp_path):
    missing = tmp_path / "absent.json"
    with pytest.raises(diff.ComparisonError) as exc:
        diff.load_snapshot_file(missing)
    assert exc.value.code == "snapshot_not_found"
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(diff.ComparisonError) as exc2:
        diff.load_snapshot_file(bad)
    assert exc2.value.code == "snapshot_unreadable"


def test_load_snapshot_file_rejects_non_object_root(tmp_path):
    array_root = tmp_path / "array.json"
    array_root.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(diff.ComparisonError) as exc:
        diff.load_snapshot_file(array_root)
    assert exc.value.code == "malformed_snapshot"


# ---------------------------------------------------------------------------
# Acceptance review additions: comparability, block presence, identity audit,
# determinism of semantic identity, renderer fidelity, CLI contract.
# ---------------------------------------------------------------------------


def _record_missing(pmid, *keys):
    """Build a record and remove keys, modelling a structurally absent block."""
    record = _record(pmid)
    for key in keys:
        del record[key]
    return record


def test_comparability_query_evolution_is_recorded_not_rejected():
    baseline = _snapshot([_record("101")])
    baseline["query"] = "original search strategy"
    target = _snapshot([_record("101")])
    target["query"] = "refined search strategy"
    result = diff.compare_snapshots(baseline, target,
                                    compared_at=FIXED_COMPARED_AT)
    scope = result["meta"]["comparability"]
    assert scope["scope"] == "same_topic"
    assert scope["query_changed"] is True
    assert scope["policy_version"] == diff.COMPARABILITY_POLICY_VERSION
    comparability = [c for c in result["changes"]
                     if c["category"] == "comparability"]
    assert [c["change_type"] for c in comparability] == ["query_changed"]
    assert comparability[0]["priority"] == 8
    assert result["meta"]["counts"]["comparability"] == 1
    assert result["meta"]["total_changes"] == 1


def test_comparability_different_topics_fail_closed():
    baseline = _snapshot([_record("101")], topic="topic alpha")
    target = _snapshot([_record("101")], topic="topic beta")
    with pytest.raises(diff.ComparisonError) as exc:
        diff.compare_snapshots(baseline, target, compared_at=FIXED_COMPARED_AT)
    assert exc.value.code == "incomparable_snapshots"
    assert "topic alpha" in str(exc.value)
    assert "topic beta" in str(exc.value)


def test_comparability_normalized_topics_are_equivalent():
    baseline = _snapshot([_record("101")], topic="  topic alpha  ")
    target = _snapshot([_record("101")], topic="topic alpha")
    baseline["query"] = target["query"] = "stable search strategy"
    result = diff.compare_snapshots(baseline, target,
                                    compared_at=FIXED_COMPARED_AT)
    assert result["meta"]["comparability"]["scope"] == "same_topic"
    assert result["meta"]["total_changes"] == 0
    assert result["meta"]["baseline_semantic_snapshot_id"] == (
        result["meta"]["target_semantic_snapshot_id"])


def test_comparability_unavailable_topics_are_status_not_guesswork():
    baseline = _snapshot([_record("101")])
    target = _snapshot([_record("101")])
    del baseline["topic"]
    target["topic"] = "   "
    result = diff.compare_snapshots(baseline, target,
                                    compared_at=FIXED_COMPARED_AT)
    assert result["meta"]["comparability"]["scope"] == "topic_unavailable"
    assert [c["change_type"] for c in result["changes"]] == [
        "scope_unverifiable"]
    assert result["changes"][0]["category"] == "comparability"


def test_comparability_partially_unavailable_topic_is_recorded():
    baseline = _snapshot([_record("101")])
    target = _snapshot([_record("101")])
    target["topic"] = ""
    result = diff.compare_snapshots(baseline, target,
                                    compared_at=FIXED_COMPARED_AT)
    assert result["meta"]["comparability"]["scope"] == (
        "topic_partially_unavailable")
    assert [c["change_type"] for c in result["changes"]] == [
        "scope_unverifiable"]
    assert result["changes"][0]["detail"]["baseline_topic_present"] is True
    assert result["changes"][0]["detail"]["target_topic_present"] is False


def test_identical_snapshots_are_flagged_and_change_free():
    snapshot = _snapshot([_record("101"), _record("102")])
    result = diff.compare_snapshots(
        snapshot, json.loads(json.dumps(snapshot)),
        compared_at=FIXED_COMPARED_AT)
    assert result["meta"]["comparability"]["identical_content"] is True
    assert result["meta"]["total_changes"] == 0
    assert result["meta"]["baseline_snapshot_id"] == (
        result["meta"]["target_snapshot_id"])


def _integrity_excluded_record(pmid):
    """Model B5's explicit non-ranking route for an integrity exclusion."""
    record = _record(pmid)
    record["assessment"] = None
    record["final_evidence_rank"] = None
    record.pop("structured_clinical_extraction")
    return record


def test_block_availability_transition_is_explicit_not_silently_skipped():
    """B5 intentionally omits extraction for excluded candidates.

    The transition to a ranked candidate therefore cannot be represented as a
    fabricated extraction or study-field diff, but it must remain auditable.
    """
    result = _compare([_integrity_excluded_record("101")], [_record("101")])
    availability = [change for change in result["changes"]
                    if change["category"] == "comparability"]
    assert [(change["change_type"], change["detail"]["block"])
            for change in availability] == [
        ("block_became_comparable", "assessment"),
        ("block_became_comparable", "final_evidence_rank"),
        ("block_became_comparable", "structured_clinical_extraction"),
    ]
    assert not [change for change in result["changes"]
                if change["category"] in {"study", "extraction", "ranking"}]


def test_null_and_absent_block_states_are_not_collapsed():
    baseline = _record("101")
    baseline["assessment"] = None
    target = _record("101")
    del target["assessment"]
    result = _compare([baseline], [target])
    availability = [change for change in result["changes"]
                    if change["category"] == "comparability"]
    assert len(availability) == 1
    assert availability[0]["change_type"] == "block_state_changed"
    assert availability[0]["detail"] == {
        "block": "assessment", "baseline_state": "null",
        "target_state": "absent",
    }


def test_missing_pmid_audit_records_are_stable_and_distinguishable():
    first = _record("", title="Unidentified A")
    second = _record("", title="Unidentified B")
    forward = diff.compare_snapshots(
        _snapshot([_record("101"), first, second]),
        _snapshot([_record("101")]), compared_at=FIXED_COMPARED_AT)
    reversed_result = diff.compare_snapshots(
        _snapshot([second, _record("101"), first]),
        _snapshot([_record("101")]), compared_at="2099-01-01T00:00:00+00:00")
    forward_unmatched = forward["meta"]["unmatched_records"]
    reversed_unmatched = reversed_result["meta"]["unmatched_records"]
    assert [record["record_digest"] for record in forward_unmatched] == [
        record["record_digest"] for record in reversed_unmatched]
    assert len({record["record_digest"] for record in forward_unmatched}) == 2
    assert all(record["snapshot"] == "baseline" for record in forward_unmatched)


def test_nested_study_assessment_availability_is_not_silently_skipped():
    baseline = _record("101", assessment={})
    result = _compare([baseline], [_record("101")])
    availability = [change for change in result["changes"]
                    if change["category"] == "comparability"]
    assert [(change["change_type"], change["detail"]["block"])
            for change in availability] == [
        ("block_became_comparable", "assessment.study_assessment")]
    assert not [change for change in result["changes"]
                if change["category"] == "study"]


def test_review_source_handoff_is_reported_when_aggregate_stays_true():
    baseline = _record("101", clinical_relevance=_relevance_dict(
        needs_review=True))
    target = _record("101", clinical_relevance=_relevance_dict(
        needs_review=False), assessment={"study_assessment": _study(
            needs_review=True)})
    result = _compare([baseline], [target])
    review = _by_type(result, "review_required_changed")
    assert len(review) == 1
    assert review[0]["baseline"]["value"] is True
    assert review[0]["target"]["value"] is True
    assert review[0]["detail"]["sources"]["relevance"] == [True, False]
    assert review[0]["detail"]["sources"]["study"] == [False, True]


def test_renderers_project_canonical_comparability_metadata():
    baseline = _snapshot([_record("101")])
    target = _snapshot([_record("101")])
    target["query"] = "refined search strategy"
    result = diff.compare_snapshots(baseline, target,
                                    compared_at=FIXED_COMPARED_AT)
    markdown = diff.render_markdown_comparison(result)
    html = diff.render_html_comparison(result)
    assert "Scope: same_topic" in markdown
    assert "Search query changed: true" in markdown
    assert "Scope: same_topic" in html
    assert "Search query changed: true" in html


def test_real_b5_serialized_cli_comparison_has_expected_artifacts(tmp_path):
    """Acceptance path: B5 build -> JSON files -> B6 loader/CLI/artifacts."""
    def article(pmid, title, abstract, publication_types=("Journal Article",)):
        return Article(pmid=pmid, title=title, abstract=abstract,
                       publication_types=publication_types)

    def candidates(items):
        assessed = [AssessedCandidate(
            item, _relevance(item.pmid, "contextual" if item.pmid == "100"
                              and item.abstract.startswith("200") else "direct"),
            assess_publication_integrity(item)) for item in items]
        selected, audited, _ = rank_and_select_candidates(
            assessed, B5_FIXED_DT, "drug condition", 3)
        return build_snapshot(
            topic="drug condition", query="drug condition",
            fetched_at=B5_FIXED_DT, ranked=selected, candidates=tuple(audited))

    baseline = candidates([
        article("100", "Drug condition randomized trial",
                "100 adults received drug A for 4 weeks. Nausea occurred."),
        article("200", "Drug condition cohort", "Adults received usual care."),
    ])
    target = candidates([
        article("100", "Drug condition randomized trial",
                "200 adults received drug A for 8 weeks. Nausea occurred."),
        article("200", "Drug condition cohort", "Adults received usual care.",
                ("Journal Article", "Retracted Publication")),
        article("300", "Drug condition randomized trial",
                "150 adults received drug A for 6 weeks. Nausea occurred."),
    ])
    baseline_path, target_path = tmp_path / "baseline.json", tmp_path / "target.json"
    baseline_path.write_text(json.dumps(baseline, sort_keys=True), encoding="utf-8")
    target_path.write_text(json.dumps(target, sort_keys=True), encoding="utf-8")
    output_dir = tmp_path / "comparison-output"
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    completed = subprocess.run(
        [sys.executable, "-m", "app.services.evidence_diff", str(baseline_path),
         str(target_path), "--out-dir", str(output_dir)],
        cwd=tmp_path, env=environment, text=True, capture_output=True, check=False)
    assert completed.returncode == 0, completed.stderr
    assert "changes: 10" in completed.stdout
    artifact_stem = "baseline_vs_target.comparison"
    result = json.loads((output_dir / f"{artifact_stem}.json").read_text(
        encoding="utf-8"))
    expected = {
        ("integrity", "integrity_changed", "200"),
        ("membership", "added", "300"),
        ("relevance", "relevance_changed", "100"),
        ("extraction", "extraction_changed", "100"),
        ("ranking", "rank_changed", "100"),
        ("review", "review_required_changed", "200"),
        ("placement", "placement_changed", "200"),
        ("comparability", "block_became_not_comparable", "200"),
    }
    actual = {(change["category"], change["change_type"], change["pmid"])
              for change in result["changes"]}
    assert expected <= actual
    unavailable_blocks = {change["detail"]["block"] for change in result["changes"]
                          if change["category"] == "comparability"}
    assert unavailable_blocks == {
        "assessment", "final_evidence_rank", "structured_clinical_extraction"}
    markdown = (output_dir / f"{artifact_stem}.md").read_text(encoding="utf-8")
    html = (output_dir / f"{artifact_stem}.html").read_text(encoding="utf-8")
    assert "PMID 200" in markdown and "integrity_changed" in markdown
    assert ">200<" in html and "integrity_changed" in html
    assert "<script" not in html.lower()


def test_cli_invalid_inputs_fail_without_success_artifacts(tmp_path):
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    output_dir = tmp_path / "no-artifacts"
    completed = subprocess.run(
        [sys.executable, "-m", "app.services.evidence_diff",
         str(tmp_path / "missing-base.json"), str(tmp_path / "missing-target.json"),
         "--out-dir", str(output_dir)],
        cwd=tmp_path, env=environment, text=True, capture_output=True, check=False)
    assert completed.returncode == 2
    assert "comparison failed [snapshot_not_found]" in completed.stderr
    assert not output_dir.exists()


def test_comparison_id_ignores_audit_timestamps_and_article_order():
    baseline = _snapshot([_record("101"), _record("102")])
    target = _snapshot([_record("101"), _record("102")])
    baseline["fetched_at"] = "2026-01-01T00:00:00+00:00"
    target["fetched_at"] = "2026-02-01T00:00:00+00:00"
    first = diff.compare_snapshots(baseline, target,
                                   compared_at=FIXED_COMPARED_AT)
    reordered_baseline = _snapshot(list(reversed(baseline["articles"])))
    reordered_target = _snapshot(list(reversed(target["articles"])))
    reordered_baseline["fetched_at"] = "2099-01-01T00:00:00+00:00"
    reordered_target["fetched_at"] = "2099-02-01T00:00:00+00:00"
    second = diff.compare_snapshots(reordered_baseline, reordered_target,
                                    compared_at="2099-03-01T00:00:00+00:00")
    assert first["meta"]["total_changes"] == second["meta"]["total_changes"] == 0
    assert first["meta"]["comparison_id"] == second["meta"]["comparison_id"]
    assert first["meta"]["baseline_snapshot_id"] != (
        second["meta"]["baseline_snapshot_id"])


def test_duplicate_missing_pmid_records_have_deterministic_audit_occurrences():
    unknown = _record("", title="Same unidentified record")
    result = diff.compare_snapshots(
        _snapshot([_record("101"), unknown, dict(unknown)]),
        _snapshot([_record("101")]), compared_at=FIXED_COMPARED_AT)
    unmatched = result["meta"]["unmatched_records"]
    assert [(record["snapshot"], record["occurrence"])
            for record in unmatched] == [("baseline", 1), ("baseline", 2)]
    assert unmatched[0]["record_digest"] == unmatched[1]["record_digest"]


@pytest.mark.parametrize("schema", ["b2", "b4", "b9", None, 7])
def test_unsupported_snapshot_versions_fail_closed(schema):
    with pytest.raises(diff.ComparisonError) as exc:
        diff.compare_snapshots(_snapshot([_record("101")], schema=schema),
                               _snapshot([_record("101")]),
                               compared_at=FIXED_COMPARED_AT)
    assert exc.value.code == "unsupported_schema_version"


def test_cli_requires_both_explicit_snapshot_paths(tmp_path):
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    completed = subprocess.run(
        [sys.executable, "-m", "app.services.evidence_diff"], cwd=tmp_path,
        env=environment, text=True, capture_output=True, check=False)
    assert completed.returncode == 2
    assert "baseline" in completed.stderr and "target" in completed.stderr


def test_markdown_escapes_stored_html_like_values():
    target = _record("102", title="<script>alert('x')</script>")
    result = _compare([_record("101")], [_record("101"), target])
    markdown = diff.render_markdown_comparison(result)
    html = diff.render_html_comparison(result)
    assert "<script" not in markdown.lower()
    assert "&lt;script&gt;" in markdown
    assert "<script" not in html.lower()
    assert "&lt;script&gt;" in html
