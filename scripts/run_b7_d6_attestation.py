"""Run one bounded B7 D6 smoke and write a credential-safe local attestation.

This operational helper is deliberately separate from the B7 production CLI.
It records a local observation of one controlled child process and validates
only the B7 artifacts that process publishes. It neither retains raw FDA
responses nor proves historical server behavior.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.regulatory_persistence import load_published_snapshot
from app.sources.regulatory.validation import API_URL, RegulatoryError


ATTESTATION_SCHEMA = "b7-d6-attestation/1.0"
SOURCE = "fda-drugsfda"
QUERY = "application_number:NDA020123"
LIMIT = 1
EXPECTED_APPLICATION = "NDA020123"
_CREDENTIAL_MARKER = re.compile(
    rb"(?:api[_-]?key|authorization|bearer|client[_-]?secret|access[_-]?token|"
    rb"password|signature|(?:[?&])sig=)",
    re.IGNORECASE,
)


class AttestationError(Exception):
    """A safe local validation failure; never include source-derived text."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact_paths(data_dir: Path, report_dir: Path, name: str) -> tuple[Path, Path, Path, Path]:
    return (
        data_dir / f"{name}.json",
        report_dir / f"{name}.md",
        report_dir / f"{name}.html",
        report_dir / f"{name}.complete",
    )


def verify_generation(data_dir: Path, report_dir: Path, name: str, credential: str) -> dict:
    """Load one completed B7 generation and return only contract-safe facts."""
    snapshot = load_published_snapshot(data_dir, report_dir, name)
    records = snapshot["records"]
    retrieval = snapshot["retrieval"]
    if not (
        snapshot["schema_version"] == "b7/1.0"
        and snapshot["source_authority"] == "FDA"
        and snapshot["source_system"] == "openFDA"
        and snapshot["document_type"] == "drug_application"
        and snapshot["jurisdiction"] == "US"
        and len(records) == LIMIT
        and records[0]["source_document_id"] == EXPECTED_APPLICATION
        and retrieval["method"] == "query"
        and retrieval["query"] == QUERY
        and retrieval["source_url"] == API_URL
        and retrieval["observed_count"] == LIMIT
        and retrieval["source_total"] == LIMIT
        and snapshot["audit"]["record_count"] == LIMIT
    ):
        raise AttestationError("post_execution_validation_failed")

    paths = _artifact_paths(data_dir, report_dir, name)
    contents = b"".join(path.read_bytes() for path in paths)
    exact_credential_absent = bool(credential) and credential.encode("utf-8") not in contents
    marker_absent = _CREDENTIAL_MARKER.search(contents) is None
    if not exact_credential_absent or not marker_absent:
        raise AttestationError("credential_redaction_failed")
    return {
        "source": {
            "authority": snapshot["source_authority"],
            "system": snapshot["source_system"],
            "jurisdiction": snapshot["jurisdiction"],
            "document_type": snapshot["document_type"],
            "schema_version": snapshot["schema_version"],
            "retrieval_method": retrieval["method"],
            "source_url": retrieval["source_url"],
            "dataset_timestamp": retrieval["dataset_timestamp"],
            "dataset_timestamp_kind": retrieval["dataset_timestamp_kind"],
        },
        "snapshot": {
            "normalized_record_count": snapshot["audit"]["record_count"],
            "application_identity": records[0]["source_document_id"],
            "snapshot_semantic_sha256": snapshot["audit"]["snapshot_semantic_sha256"],
            "raw_response_sha256": retrieval["raw_response_sha256"],
        },
        "artifacts": {
            "sha256": {path.name: _sha256(path) for path in paths[:3]},
            "completion_marker_verified": True,
            "json_markdown_html_consistent": True,
        },
        "credential_redaction": {
            "exact_credential_absent": True,
            "credential_url_markers_absent": True,
            "passed": True,
        },
    }


def write_attestation(path: Path, attestation: dict, credential: str) -> None:
    """Write canonical JSON only after rejecting accidental credential retention."""
    encoded = (json.dumps(attestation, sort_keys=True, indent=2) + "\n").encode("utf-8")
    if credential and credential.encode("utf-8") in encoded:
        raise AttestationError("credential_redaction_failed")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)


def run_controlled_d6(data_dir: Path, report_dir: Path, name: str, *, timeout: int = 240) -> dict:
    """Execute exactly one approved CLI command and attest its local outcome."""
    credential = os.environ.get("OPENFDA_API_KEY", "")
    started_at = _utc_now()
    command_identity = {
        "python_module": "app.sources.regulatory.cli",
        "source": SOURCE,
        "query": QUERY,
        "limit": LIMIT,
        "save": True,
        "pdf_or_linked_document_retrieval": False,
    }
    attestation = {
        "schema_version": ATTESTATION_SCHEMA,
        "execution": {
            "started_at": started_at,
            "finished_at": None,
            "environment_openfda_api_key_present": bool(credential),
            "command_identity": command_identity,
            "process_exit_code": None,
            "outcome_classification": None,
        },
        "source": None,
        "snapshot": None,
        "artifacts": None,
        "credential_redaction": None,
        "limitation": "An execution attestation is an auditable local observation, not cryptographic proof of historical FDA server behavior.",
    }
    if not credential:
        attestation["execution"]["finished_at"] = _utc_now()
        attestation["execution"]["outcome_classification"] = "environment_missing"
        return attestation

    command = [
        sys.executable, "-m", "app.sources.regulatory.cli", "--source", SOURCE,
        "--query", QUERY, "--limit", str(LIMIT), "--save", "--data-dir",
        str(data_dir), "--report-dir", str(report_dir), "--name", name,
    ]
    try:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        attestation["execution"]["finished_at"] = _utc_now()
        attestation["execution"]["outcome_classification"] = "process_start_failed"
        return attestation
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        attestation["execution"]["process_exit_code"] = process.returncode
        attestation["execution"]["outcome_classification"] = "process_timeout"
    else:
        attestation["execution"]["process_exit_code"] = process.returncode
        if process.returncode != 0:
            attestation["execution"]["outcome_classification"] = "cli_failed"
        else:
            try:
                verified = verify_generation(data_dir, report_dir, name, credential)
            except (AttestationError, OSError, ValueError, RegulatoryError):
                attestation["execution"]["outcome_classification"] = "post_execution_validation_failed"
            else:
                attestation.update(verified)
                attestation["execution"]["outcome_classification"] = "success"
    attestation["execution"]["finished_at"] = _utc_now()
    return attestation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args(argv)
    if args.timeout < 1:
        parser.error("--timeout must be positive")
    output = args.report_dir / f"{args.name}.attestation.json"
    try:
        attestation = run_controlled_d6(args.data_dir, args.report_dir, args.name, timeout=args.timeout)
        write_attestation(output, attestation, os.environ.get("OPENFDA_API_KEY", ""))
    except (AttestationError, OSError, ValueError):
        return 2
    return 0 if attestation["execution"]["outcome_classification"] == "success" else 2


if __name__ == "__main__":
    raise SystemExit(main())