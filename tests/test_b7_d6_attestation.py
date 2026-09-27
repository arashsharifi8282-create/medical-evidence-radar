"""Offline contract tests for the controlled, credential-safe D6 attestation."""
import importlib.util
import hashlib
import json
from pathlib import Path

from app.services.regulatory_normalizer import normalize_response
from app.services.regulatory_persistence import save_snapshot
from tests.test_b7_regulatory import source


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_b7_d6_attestation.py"
SPEC = importlib.util.spec_from_file_location("run_b7_d6_attestation", SCRIPT)
attestation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(attestation)


def _saved_d6_generation(tmp_path):
    response = source()
    response["results"] = [response["results"][0]]
    response["results"][0]["application_number"] = "NDA020123"
    response["meta"]["results"].update(total=1, limit=1, skip=0)
    snapshot = normalize_response(
        response,
        method="query",
        scope="application_number:NDA020123",
        retrieved_at="2026-09-27T00:00:00Z",
        raw_bytes=b"synthetic D6 response",
    )
    data_dir, report_dir = tmp_path / "data", tmp_path / "reports"
    save_snapshot(snapshot, data_dir, report_dir, "d6")
    return data_dir, report_dir


def test_b7_d6_attestation_verifies_completed_generation_without_retaining_credential(tmp_path):
    data_dir, report_dir = _saved_d6_generation(tmp_path)
    credential = "ROTATED_TEST_CREDENTIAL"
    verified = attestation.verify_generation(data_dir, report_dir, "d6", credential)
    record = {
        "schema_version": attestation.ATTESTATION_SCHEMA,
        "execution": {"environment_openfda_api_key_present": True, "process_exit_code": 0,
                      "outcome_classification": "success"},
        **verified,
        "limitation": "local observation only",
    }
    output = report_dir / "d6.attestation.json"
    attestation.write_attestation(output, record, credential)
    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted["snapshot"]["application_identity"] == "NDA020123"
    assert persisted["snapshot"]["normalized_record_count"] == 1
    assert persisted["source"]["schema_version"] == "b7/1.0"
    assert persisted["artifacts"]["completion_marker_verified"] is True
    assert persisted["credential_redaction"]["passed"] is True
    assert credential not in output.read_text(encoding="utf-8")


def test_b7_d6_attestation_rejects_generated_credential_marker(tmp_path):
    data_dir, report_dir = _saved_d6_generation(tmp_path)
    markdown = report_dir / "d6.md"
    markdown.write_text("api_key=not-a-secret", encoding="utf-8")
    marker = report_dir / "d6.complete"
    manifest = json.loads(marker.read_text(encoding="utf-8"))
    manifest["files"][markdown.name] = hashlib.sha256(markdown.read_bytes()).hexdigest()
    marker.write_text(json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    try:
        attestation.verify_generation(data_dir, report_dir, "d6", "ROTATED_TEST_CREDENTIAL")
    except Exception as error:
        assert type(error).__name__ in {"AttestationError", "RegulatoryError"}
    else:
        raise AssertionError("credential-bearing artifact marker was accepted")


def test_b7_d6_attestation_environment_missing_is_safe(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENFDA_API_KEY", raising=False)
    result = attestation.run_controlled_d6(tmp_path / "data", tmp_path / "reports", "d6")
    assert result["execution"]["environment_openfda_api_key_present"] is False
    assert result["execution"]["process_exit_code"] is None
    assert result["execution"]["outcome_classification"] == "environment_missing"
    assert result["source"] is None


def test_b7_d6_attestation_process_start_failure_is_safe(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENFDA_API_KEY", "ROTATED_TEST_CREDENTIAL")
    monkeypatch.setattr(attestation.subprocess, "Popen", lambda *args, **kwargs: (_ for _ in ()).throw(OSError()))
    result = attestation.run_controlled_d6(tmp_path / "data", tmp_path / "reports", "d6")
    assert result["execution"]["process_exit_code"] is None
    assert result["execution"]["outcome_classification"] == "process_start_failed"