"""Controlled offline B7 acceptance probes; expectations independent of production."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures" / "b7_regulatory"


def source():
    return json.loads((FIX / "query_response.json").read_bytes())


def test_b7_fixture_checksums():
    manifest = json.loads((FIX / "manifest.json").read_bytes())
    for name, checksum in manifest["checksums"].items():
        assert hashlib.sha256((FIX / name).read_bytes()).hexdigest() == checksum
    assert json.loads((FIX / "expected.json").read_bytes())["record_count"] == 2
    adversarial = json.loads((FIX / "adversarial_expectations.json").read_bytes())
    assert len(adversarial["cases"]) == 8
    assert {case["expected_code"] for case in adversarial["cases"]} >= {
        "invalid_json", "invalid_zip", "malformed_source", "incomplete_ingestion", "artifact_write_failed", "artifact_corrupt"}


def test_b7_normalization_scope_status_and_provenance():
    from app.services.regulatory_normalizer import normalize_response
    snapshot = normalize_response(source(), method="query", scope="application_number:NDA9990*",
                                  retrieved_at="2026-09-26T00:00:00Z", raw_bytes=(FIX / "query_response.json").read_bytes())
    expected = json.loads((FIX / "expected.json").read_bytes())
    assert [r["source_document_id"] for r in snapshot["records"]] == expected["ids"]
    assert snapshot["source_authority"] == expected["source_authority"]
    assert snapshot["jurisdiction"] == expected["jurisdiction"]
    assert snapshot["records"][0]["document_status"] == "unknown"
    assert snapshot["records"][0]["products"][1]["marketing_status"] == "Discontinued"
    assert snapshot["records"][0]["submissions"][0]["submission_status_date"] == "2024-01-03"
    assert snapshot["records"][0]["raw_field_state"]["sponsor_name"] == "present"
    assert snapshot["records"][1]["raw_field_state"]["sponsor_name"] == "null"
    assert "pmid" not in snapshot["records"][0]


@pytest.mark.parametrize("edit,code", [
    (lambda s: s["results"][0].pop("application_number"), "missing_identifier"),
    (lambda s: s["results"][1].update(application_number="NDA999001"), "duplicate_document_id"),
    (lambda s: s["results"][0]["products"][0].pop("product_number"), "missing_nested_identifier"),
    (lambda s: s["results"][0]["submissions"][0].update(submission_status_date="20240230"), "invalid_source_date"),
    (lambda s: s["results"][0].update(sponsor_name=42), "malformed_source"),
])
def test_b7_invalid_records_fail_closed(edit, code):
    from app.services.regulatory_normalizer import normalize_response
    from app.sources.regulatory.validation import RegulatoryError
    sample = source()
    edit(sample)
    with pytest.raises(RegulatoryError) as error:
        normalize_response(sample, method="query", scope="example", retrieved_at="2026-09-26T00:00:00Z")
    assert error.value.code == code


def test_b7_semantic_reordering_raw_only_and_dataset_timestamp():
    from app.services.regulatory_normalizer import normalize_response
    def normalize(value):
        return normalize_response(value, method="query", scope="example", retrieved_at="2026-09-26T00:00:00Z")
    initial = normalize(source())
    reordered = source()
    reordered["results"].reverse()
    reordered["results"][1]["products"].reverse()
    assert normalize(reordered)["audit"]["snapshot_semantic_sha256"] == initial["audit"]["snapshot_semantic_sha256"]
    raw_only = source()
    raw_only["results"][0]["new_field"] = "unmapped"
    newer = normalize(raw_only)
    assert newer["records"][0]["content_digest"] == initial["records"][0]["content_digest"]
    assert newer["records"][0]["raw_source_reference"]["record_sha256"] != initial["records"][0]["raw_source_reference"]["record_sha256"]
    stamped = source()
    stamped["meta"]["last_updated"] = "2026-09-27"
    assert normalize(stamped)["audit"]["snapshot_semantic_sha256"] == initial["audit"]["snapshot_semantic_sha256"]
    changed = source()
    changed["results"][0]["products"][0]["marketing_status"] = "Prescription"
    assert normalize(changed)["records"][0]["content_digest"] != initial["records"][0]["content_digest"]


def test_b7_renderers_and_b6_rejection(tmp_path):
    from app.services.regulatory_normalizer import normalize_response
    from app.services.regulatory_persistence import save_snapshot, render_markdown, render_html, load_snapshot
    snapshot = normalize_response(source(), method="query", scope="example", retrieved_at="2026-09-26T00:00:00Z")
    paths = save_snapshot(snapshot, tmp_path / "data", tmp_path / "reports", "synthetic")
    loaded = load_snapshot(paths[0])
    assert loaded == snapshot
    assert all(p.exists() for p in paths)
    assert "&lt;script&gt;" in render_markdown(loaded)
    assert "&lt;script&gt;" in render_html(loaded)
    assert "Discontinued" in render_html(loaded)


def test_b7_persisted_duplicate_json_keys_fail_closed(tmp_path):
    from app.services.regulatory_persistence import load_snapshot
    from app.sources.regulatory.validation import RegulatoryError
    file = tmp_path / "duplicates.json"
    file.write_text('{"schema_version":"b7/1.0","schema_version":"b7/1.0"}', encoding="utf-8")
    with pytest.raises(RegulatoryError) as error:
        load_snapshot(file)
    assert error.value.code == "artifact_corrupt"


def test_b7_native_b6_rejection_fails_closed_with_shape_error():
    """Native B7 is fail-closed by unchanged B6 before version validation."""
    from app.services.evidence_diff import compare_snapshots, ComparisonError
    from app.services.regulatory_normalizer import normalize_response
    result = normalize_response(source(), method="query", scope="x", retrieved_at="2026-09-26T00:00:00Z")
    with pytest.raises(ComparisonError) as error:
        compare_snapshots(result, result, "2026-09-26T00:00:00Z")
    assert error.value.code == "malformed_snapshot"


def test_b7_unsupported_snapshot_version_and_no_overwrite(tmp_path):
    from app.services.regulatory_normalizer import normalize_response
    from app.services.regulatory_persistence import save_snapshot, validate_snapshot
    from app.sources.regulatory.validation import RegulatoryError
    result = normalize_response(source(), method="query", scope="x", retrieved_at="2026-09-26T00:00:00Z")
    with pytest.raises(RegulatoryError) as error:
        validate_snapshot({**result, "schema_version": "b7/2.0"})
    assert error.value.code == "unsupported_schema_version"
    save_snapshot(result, tmp_path / "data", tmp_path / "reports", "one")
    with pytest.raises(RegulatoryError) as error:
        save_snapshot(result, tmp_path / "data", tmp_path / "reports", "one")
    assert error.value.code == "artifact_write_failed"
    marker = json.loads((tmp_path / "reports" / "one.complete").read_text(encoding="utf-8"))
    assert marker["schema_version"] == "b7-completion/1.0"
    assert marker["files"]["one.json"] == hashlib.sha256((tmp_path / "data" / "one.json").read_bytes()).hexdigest()


@pytest.mark.parametrize("mutation", [
    lambda x: x["records"][0]["products"][0].update(marketing_status=37),
    lambda x: x["records"][0]["submissions"][0]["application_docs"][0].update(date="2024-22-01"),
    lambda x: x["records"][0]["provenance"].pop("field_paths"),
    lambda x: x["records"][0]["raw_source_reference"].update(record_sha256="bad"),
    lambda x: x["records"][0]["canonical_identity"].update(source_document_id="wrong"),
    lambda x: x["records"][0]["products"][0]["source_fields"].pop("brand_name"),
    lambda x: x["records"][0]["review_reasons"].append(23),
    lambda x: x["retrieval"].update(partition_count=1),
    lambda x: x["retrieval"].update(source_url="https://evil.example/"),
    lambda x: x["audit"].update(snapshot_semantic_sha256="bad"),
    lambda x: x["records"][0].update(unapproved_field="surprise"),
    lambda x: x["records"][0]["products"][0].update(marketing_status="Discontinued"),
    lambda x: x["records"][0].update(content_digest="0" * 64),
    lambda x: x["records"][0].update(content_digest=42),
    lambda x: x["retrieval"].update(retrieved_at=42),
    lambda x: x["retrieval"].update(dataset_timestamp=42),
    lambda x: x["records"][0]["provenance"].update(source_record_locator=42),
    lambda x: x["records"][0]["products"][0]["source_fields"]["brand_name"].update(path="results[99].brand_name"),
    lambda x: x["records"][0]["products"][0]["source_fields"]["brand_name"].update(raw_value="forged"),
])
def test_b7_persisted_schema_rejects_nested_corruption(mutation):
    from app.services.regulatory_normalizer import normalize_response
    from app.services.regulatory_persistence import validate_snapshot
    from app.sources.regulatory.validation import RegulatoryError
    snapshot = normalize_response(source(), method="query", scope="x", retrieved_at="2026-09-26T00:00:00Z")
    mutation(snapshot)
    with pytest.raises(RegulatoryError) as error:
        validate_snapshot(snapshot)
    assert error.value.code == "artifact_corrupt"


def test_b7_nested_provenance_and_raw_loss():
    from app.services.regulatory_normalizer import normalize_response
    snapshot = normalize_response(source(), method="query", scope="x", retrieved_at="2026-09-26T00:00:00Z")
    row = snapshot["records"][0]
    assert row["provenance"]["document_type"] == "drug_application"
    assert row["provenance"]["license_note"]
    ingredient = row["products"][1]["active_ingredients"][0]
    assert ingredient["source_fields"]["name"]["raw_value"] == "Example"
    assert ingredient["source_fields"]["name"]["path"].endswith(".active_ingredients[0].name")
    assert any("not retained" in warning for warning in snapshot["audit"]["warnings"])
    assert "unknown" in " ".join(snapshot["audit"]["warnings"]).lower()


def test_b7_native_b6_cli_no_success_artifacts(tmp_path, capsys):
    from app.services.evidence_diff import main as b6_main
    from app.services.regulatory_normalizer import normalize_response
    from app.services.regulatory_persistence import save_snapshot
    snapshot = normalize_response(source(), method="query", scope="x", retrieved_at="2026-09-26T00:00:00Z")
    path = save_snapshot(snapshot, tmp_path / "data", tmp_path / "report", "native")[0]
    with pytest.raises(SystemExit) as error:
        b6_main([str(path), str(path), "--out-dir", str(tmp_path / "b6")])
    assert error.value.code == 2
    assert "malformed_snapshot" in capsys.readouterr().err
    assert not (tmp_path / "b6").exists()


@pytest.mark.parametrize("edit,code", [
    (lambda s: s["results"][0]["submissions"][0].pop("submission_type"), "missing_nested_identifier"),
    (lambda s: s["results"][0]["submissions"][0].pop("submission_number"), "missing_nested_identifier"),
    (lambda s: s["results"][0]["products"][0].update(active_ingredients={}), "malformed_source"),
    (lambda s: s["results"][0]["submissions"][0].update(application_docs="bad"), "malformed_source"),
    (lambda s: s["results"][0]["submissions"][0]["application_docs"][0].update(date=""), "invalid_source_date"),
    (lambda s: s["results"][0].update(products=None), "malformed_source"),
    (lambda s: s["meta"].update(last_updated="2026-02-30"), "invalid_source_date"),
])
def test_b7_adversarial_nested_source(edit, code):
    from app.services.regulatory_normalizer import normalize_response
    from app.sources.regulatory.validation import RegulatoryError
    data = source()
    edit(data)
    with pytest.raises(RegulatoryError) as error:
        normalize_response(data, method="query", scope="x", retrieved_at="2026-09-26T00:00:00Z")
    assert error.value.code == code


def test_b7_optional_absent_null_empty_and_unknown_status():
    from app.services.regulatory_normalizer import normalize_response
    data = source()
    product = data["results"][0]["products"][0]
    product["brand_name"] = ""
    product["marketing_status"] = "UNMAPPED-CODE"
    data["results"][0]["submissions"][0]["submission_status"] = ""
    row = normalize_response(data, method="query", scope="x", retrieved_at="2026-09-26T00:00:00Z")["records"][0]
    assert row["products"][1]["brand_name"] is None
    assert row["products"][1]["source_fields"]["brand_name"]["raw_value"] == ""
    assert row["products"][1]["source_fields"]["dosage_form"]["state"] == "absent"
    assert row["products"][1]["marketing_status"] == "UNMAPPED-CODE"
    assert row["submissions"][0]["submission_status"] is None
    assert row["document_status"] == "unknown"
    assert {"empty_optional_value", "unknown_product_marketing_status"}.issubset(row["review_reasons"])


def test_b7_semantic_hash_nested_reordering_and_changes():
    from app.services.regulatory_normalizer import normalize_response
    def normalized(x):
        return normalize_response(x, method="query", scope="x", retrieved_at="2026-09-26T00:00:00Z")
    before = source()
    base = normalized(before)["records"][0]
    after = source()
    after["results"][0]["submissions"].reverse()
    after["results"][0]["products"][0]["active_ingredients"].append({"name": "Other", "strength": "2 mg"})
    after["results"][0]["products"][0]["active_ingredients"].reverse()
    expected = normalized(after)["records"][0]["content_digest"]
    after["results"][0]["products"][0]["active_ingredients"].reverse()
    assert normalized(after)["records"][0]["content_digest"] == expected
    assert expected != base["content_digest"]
    after = source()
    after["results"][0]["submissions"][0]["application_docs"].append({"id": "new", "date": "20260101"})
    assert normalized(after)["records"][0]["content_digest"] != base["content_digest"]


def test_b7_canonical_nested_permutations_byte_equivalent_semantics():
    from app.services.regulatory_normalizer import normalize_response
    from app.services.regulatory_persistence import canonical_json
    before = source()
    before["results"][0]["products"][0]["active_ingredients"].append({"name": "Other", "strength": "2 mg"})
    before["results"][0]["submissions"][0]["application_docs"].append({"id": "two", "date": "20260101"})
    after = copy.deepcopy(before)
    after["results"].reverse()
    first = after["results"][1]
    first["products"].reverse()
    first["submissions"].reverse()
    first["products"][1]["active_ingredients"].reverse()
    first["submissions"][1]["application_docs"].reverse()
    def normalized(data):
        return normalize_response(data, method="query", scope="same", retrieved_at="2026-09-26T00:00:00Z")
    a, b = normalized(before), normalized(after)
    assert a["audit"]["snapshot_semantic_sha256"] == b["audit"]["snapshot_semantic_sha256"]
    assert [r["content_digest"] for r in a["records"]] == [r["content_digest"] for r in b["records"]]
    assert canonical_json(a).encode("utf-8") == canonical_json(normalized(before)).encode("utf-8")
    assert canonical_json(a).endswith("\n")
    assert a["records"][0]["raw_source_reference"]["record_sha256"] != b["records"][0]["raw_source_reference"]["record_sha256"]


def test_b7_same_name_different_strength_ingredient_order_is_semantic_invariant():
    from app.services.regulatory_normalizer import normalize_response
    one = source()
    ingredients = one["results"][0]["products"][0]["active_ingredients"]
    ingredients.append({"name": "Example", "strength": "2 mg"})
    two = copy.deepcopy(one)
    two["results"][0]["products"][0]["active_ingredients"].reverse()
    def content(value):
        return normalize_response(value, method="query", scope="same",
                                  retrieved_at="2026-09-26T00:00:00Z")["records"][0]["content_digest"]
    assert content(one) == content(two)


def test_b7_rendered_counts_ids_statuses_match_json(tmp_path):
    from app.services.regulatory_normalizer import normalize_response
    from app.services.regulatory_persistence import save_snapshot, load_snapshot
    snapshot = normalize_response(source(), method="query", scope="x", retrieved_at="2026-09-26T00:00:00Z")
    paths = save_snapshot(snapshot, tmp_path / "data", tmp_path / "reports", "projection")
    loaded = load_snapshot(paths[0])
    md, page = (p.read_text(encoding="utf-8") for p in paths[1:3])
    assert "- Records: 2" in md and "Records: 2" in page
    assert page.count("<article") == len(loaded["records"])
    for row in loaded["records"]:
        for output in (md, page):
            assert output.count("## Application " + row["source_document_id"]) == 1
            assert f"Products: {len(row['products'])}; submissions: {len(row['submissions'])}" in output
            for p in row["products"]:
                assert "marketing_status (product only): " + p["marketing_status"] in output
            for s in row["submissions"]:
                assert "source status " + str(s["submission_status"]) in output
    assert "<script>" not in page and "&lt;script&gt;" in page


@pytest.mark.parametrize("edit", [
    lambda x: x["meta"].update(terms="https://open.fda.gov/terms/?api_key=LEAK"),
    lambda x: x["results"][0]["submissions"][0]["application_docs"][0].update(url="https://open.fda.gov/doc.pdf?api_key=LEAK"),
])
def test_b7_source_auth_urls_never_persist(edit):
    from app.services.regulatory_normalizer import normalize_response
    from app.sources.regulatory.validation import RegulatoryError
    data = source()
    edit(data)
    with pytest.raises(RegulatoryError) as error:
        normalize_response(data, method="query", scope="x", retrieved_at="2026-09-26T00:00:00Z")
    assert error.value.code == "malformed_source"


@pytest.mark.parametrize("scope", ["application_number:NDA020123+api_key=LEAK",
    "patient_id:example", "sponsor_name:person@example.test", "application_number:123-45-6789"])
def test_b7_persisted_query_scope_policy_rejects_unsafe_audit_metadata(scope):
    from app.services.regulatory_normalizer import normalize_response
    from app.services.regulatory_persistence import validate_snapshot
    from app.sources.regulatory.validation import RegulatoryError
    snapshot = normalize_response(source(), method="query", scope=scope,
                                  retrieved_at="2026-09-26T00:00:00Z")
    with pytest.raises(RegulatoryError) as error:
        validate_snapshot(snapshot)
    assert error.value.code == "artifact_corrupt"


def test_b7_persisted_top_level_state_and_container_provenance_are_consistent():
    from app.services.regulatory_normalizer import normalize_response
    from app.services.regulatory_persistence import validate_snapshot
    from app.sources.regulatory.validation import RegulatoryError
    value = normalize_response(source(), method="query", scope="x", retrieved_at="2026-09-26T00:00:00Z")
    for edit in (
        lambda row: row["raw_field_state"].update(products="absent"),
        lambda row: row["products"][0]["source_fields"]["active_ingredients"].update(raw_value=[]),
        lambda row: row["submissions"][0]["source_fields"]["application_docs"].update(raw_value=[]),
        lambda row: row["products"][1]["active_ingredients"][0]["source_fields"]["name"].update(path="results[0].products[99].active_ingredients[0].name"),
    ):
        mutated = copy.deepcopy(value)
        edit(mutated["records"][0])
        with pytest.raises(RegulatoryError) as exc:
            validate_snapshot(mutated)
        assert exc.value.code == "artifact_corrupt"


def test_b7_html_has_independent_structured_metadata_and_exact_doc_link_text():
    from app.services.regulatory_normalizer import normalize_response
    from app.services.regulatory_persistence import render_html, render_markdown
    record = normalize_response(source(), method="query", scope="x", retrieved_at="2026-09-26T00:00:00Z")
    link = record["records"][0]["submissions"][0]["application_docs"][0]
    for output in (render_markdown(record), render_html(record)):
        for field in ("id", "date", "type", "url"):
            assert str(link[field]) in output
        assert "http://www.accessdata.fda.gov/example.pdf" in output
        assert "&lt;script&gt;" in output and "<script>" not in output
    page = render_html(record)
    assert "<article" in page and "<section" in page and "<pre>" not in page