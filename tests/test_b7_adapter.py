"""Offline transport, bulk integrity, CLI and security regression checks."""
import copy
import io
import json
import zipfile

import pytest

from app.sources.regulatory.fda_openfda import FDAClient
from app.sources.regulatory.validation import RegulatoryError, extract_zip, safe_url
from app.sources.regulatory.cli import main
from tests.test_b7_regulatory import source


class Response:
    def __init__(self, payload, status=200, headers=None):
        self.content = payload
        self.status_code = status
        self.headers = headers or {}

    def iter_content(self, chunk_size):
        yield self.content

    def close(self):
        pass


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return next(self.responses)


def payload(obj):
    return json.dumps(obj).encode()


def archive(data, member="part.json"):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(member, payload(data))
    return out.getvalue()


def bulk_input():
    url = "https://download.open.fda.gov/drug/drugsfda/drug-drugsfda-0001-of-0001.json.zip"
    manifest = {"results": {"drug": {"drugsfda": {"export_date": "2026-09-26", "total_records": 2,
        "partitions": [{"file": url, "records": 2}]}}}}
    return manifest, archive(source()), url


def test_b7_query_fake_transport_and_explicit_key():
    session = Session([Response(payload(source()))])
    client = FDAClient(session=session, api_key="LOCAL_TEST_ONLY")
    snapshot = client.query("application_number:NDA9990*", limit=2, retrieved_at="2026-09-26T00:00:00Z")
    assert snapshot["retrieval"]["completeness"] == "bounded_query"
    assert len(session.calls) == 1
    assert session.calls[0][0] == "https://api.fda.gov/drug/drugsfda.json"
    assert session.calls[0][1]["allow_redirects"] is False
    assert "LOCAL_TEST_ONLY" not in json.dumps(snapshot)


def test_b7_bulk_fake_transport_end_to_end(tmp_path):
    manifest, zip_bytes, url = bulk_input()
    client = FDAClient(session=Session([Response(payload(manifest)), Response(zip_bytes)]), api_key=None)
    snapshot = client.bulk(retrieved_at="2026-09-26T00:00:00Z")
    assert snapshot["retrieval"]["completeness"] == "complete_bulk"
    assert snapshot["retrieval"]["partition_digests"][0]["url"] == url
    assert main(["--source", "fda-drugsfda", "--manifest", "--save",
                 "--data-dir", str(tmp_path / "data"), "--report-dir", str(tmp_path / "reports")],
                client=FDAClient(session=Session([Response(payload(manifest)), Response(zip_bytes)]))) == 0
    assert (tmp_path / "reports" / "fda_observation.complete").exists()


def test_b7_bulk_incomplete_does_not_write(tmp_path):
    manifest, zip_bytes, _ = bulk_input()
    manifest["results"]["drug"]["drugsfda"]["total_records"] = 3
    result = main(["--source", "fda-drugsfda", "--manifest", "--save",
                   "--data-dir", str(tmp_path / "data"), "--report-dir", str(tmp_path / "reports")],
                  client=FDAClient(session=Session([Response(payload(manifest)), Response(zip_bytes)])))
    assert result == 2
    assert not (tmp_path / "reports").exists()


@pytest.mark.parametrize("url", ["http://api.fda.gov/download.json", "https://evil.test/drug/drugsfda/a.json.zip",
    "https://download.open.fda.gov/drug/drugsfda/../a.json.zip", "https://api.fda.gov/download.json?api_key=secret"])
def test_b7_unsafe_urls(url):
    with pytest.raises(RegulatoryError, match="Regulatory source validation failed") as e:
        safe_url(url, partition="zip" in url and "api.fda.gov" not in url)
    assert e.value.code == "unsafe_url"


def test_b7_unsafe_redirect_does_not_send_key():
    session = Session([Response(b"", 302, {"Location": "https://attacker.test/key"})])
    with pytest.raises(RegulatoryError) as e:
        FDAClient(session=session, api_key="LOCAL_TEST_ONLY").query("example", limit=1)
    assert e.value.code == "unsafe_url"
    assert len(session.calls) == 1


def test_b7_zip_traversal():
    with pytest.raises(RegulatoryError) as e:
        extract_zip(archive(source(), "../escape.json"))
    assert e.value.code == "invalid_zip"


def test_b7_cli_rejects_other_authorities_without_network(capsys):
    with pytest.raises(SystemExit) as e:
        main(["--source", "ema", "--query", "example"])
    assert e.value.code == 2


def test_b7_bulk_rejects_missing_partition_and_unsafe_member():
    manifest, zipped, url = bulk_input()
    manifest["results"]["drug"]["drugsfda"]["partitions"].append({"file": url + "-other", "records": 0})
    with pytest.raises(RegulatoryError):
        FDAClient(session=Session([Response(payload(manifest)), Response(zipped)])).bulk()
    with pytest.raises(RegulatoryError) as error:
        extract_zip(archive(source(), "../escape.json"))
    assert error.value.code == "invalid_zip"


def test_b7_duplicate_nested_ids_and_unknown_doc_id():
    from app.services.regulatory_normalizer import normalize_response
    for section, key in (("products", "product_number"), ("submissions", "submission_number")):
        record = source()
        record["results"][0][section][1][key] = record["results"][0][section][0][key]
        if section == "submissions":
            record["results"][0][section][1]["submission_type"] = "ORIG"
        with pytest.raises(RegulatoryError) as error:
            normalize_response(record, method="query", scope="x", retrieved_at="2026-09-26T00:00:00Z")
        assert error.value.code == "duplicate_nested_id"
    record = source()
    docs = record["results"][0]["submissions"][0]["application_docs"]
    docs.append(dict(docs[0]))
    observation = normalize_response(record, method="query", scope="x", retrieved_at="2026-09-26T00:00:00Z")
    assert len(observation["records"][0]["submissions"][0]["application_docs"]) == 2


def test_b7_malformed_json_and_zip_size():
    from app.sources.regulatory.validation import parse_json
    with pytest.raises(RegulatoryError) as error:
        parse_json(b'{"a":1,"a":2}')
    assert error.value.code == "invalid_json"
    with pytest.raises(RegulatoryError) as error:
        extract_zip(b"broken archive")
    assert error.value.code == "invalid_zip"


def test_b7_cli_query_mode_offline(tmp_path):
    class Fake:
        def query(self, expression, limit):
            from app.services.regulatory_normalizer import normalize_response
            return normalize_response(source(), method="query", scope=expression,
                                      retrieved_at="2026-09-26T00:00:00Z")
    assert main(["--source", "fda-drugsfda", "--query", "synthetic", "--save",
                 "--data-dir", str(tmp_path / "data"), "--report-dir", str(tmp_path / "reports")],
                client=Fake()) == 0
    assert (tmp_path / "data" / "fda_observation.json").exists()


@pytest.mark.parametrize("bad", ["two", None, True, -1])
def test_b7_bulk_invalid_partition_count_fails_before_network(bad):
    manifest, zipped, _ = bulk_input()
    manifest["results"]["drug"]["drugsfda"]["partitions"][0]["records"] = bad
    session = Session([Response(payload(manifest)), Response(zipped)])
    with pytest.raises(RegulatoryError):
        FDAClient(session=session).bulk()
    assert len(session.calls) == 1


def test_b7_write_failure_rolls_back(tmp_path, monkeypatch):
    from app.services import regulatory_persistence as storage
    from app.services.regulatory_normalizer import normalize_response
    snapshot = normalize_response(source(), method="query", scope="x", retrieved_at="2026-09-26T00:00:00Z")
    original = storage.os.replace
    count = 0
    def fail_after_one(src, dst):
        nonlocal count
        count += 1
        if count == 2:
            raise OSError("injected failure")
        return original(src, dst)
    monkeypatch.setattr(storage.os, "replace", fail_after_one)
    with pytest.raises(RegulatoryError) as error:
        storage.save_snapshot(snapshot, tmp_path / "data", tmp_path / "reports", "failure")
    assert error.value.code == "artifact_write_failed"
    assert not list(tmp_path.rglob("*.complete"))
    assert not list(tmp_path.rglob("*.json"))
    assert not list(tmp_path.rglob(".b7-*"))


@pytest.mark.parametrize("scope", ["application_number:A+api_key=LEAK", "application_number:A+client-secret=LEAK",
    "patient_name:Example", "email:person@example.test", "sponsor_name:person@example.test",
    "application_number:123-45-6789", "application_number:555-010-1234", "application_number:NDA\n020123"])
def test_b7_query_secret_or_obvious_patient_scope_rejected_before_request(scope):
    session = Session([])
    with pytest.raises(RegulatoryError) as error:
        FDAClient(session=session, api_key="LOCAL_TEST_ONLY").query(scope)
    assert error.value.code == "invalid_scope"
    assert session.calls == []


@pytest.mark.parametrize("scope", ["application_number:NDA020123", "products.brand_name:semaglutide",
    "sponsor_name:(Example AND therapy)", "indications_and_usage:hypertension"])
def test_b7_biomedical_query_scope_is_allowed(scope):
    session = Session([Response(payload(source()))])
    snapshot = FDAClient(session=session, api_key="LOCAL_TEST_ONLY").query(scope, limit=2,
                                                                             retrieved_at="2026-09-26T00:00:00Z")
    assert snapshot["retrieval"]["query"] == scope
    assert len(session.calls) == 1


def test_b7_query_source_key_does_not_persist_in_renderers(tmp_path):
    from app.services.regulatory_persistence import save_snapshot
    session = Session([Response(payload(source()))])
    snapshot = FDAClient(session=session, api_key="LOCAL_TEST_ONLY").query("application_number:NDA9990*", limit=2)
    paths = save_snapshot(snapshot, tmp_path / "data", tmp_path / "reports", "no_secret")
    assert all("LOCAL_TEST_ONLY" not in path.read_text(encoding="utf-8") for path in paths)
    assert "LOCAL_TEST_ONLY" not in str(session.calls[0][0])


@pytest.mark.parametrize("mode", ["missing", "corrupt", "count", "truncated"])
def test_b7_bulk_corrupt_or_incomplete_never_publishes(tmp_path, mode):
    manifest, zipped, url = bulk_input()
    if mode == "missing":
        responses = [Response(payload(manifest)), Response(b"", status=404)]
    elif mode == "corrupt":
        responses = [Response(payload(manifest)), Response(b"not-a-zip")]
    elif mode == "count":
        manifest["results"]["drug"]["drugsfda"]["partitions"][0]["records"] = 1
        manifest["results"]["drug"]["drugsfda"]["total_records"] = 1
        responses = [Response(payload(manifest)), Response(zipped)]
    else:
        responses = [Response(payload(manifest)), Response(zipped[:20])]
    assert main(["--source", "fda-drugsfda", "--manifest", "--save",
                 "--data-dir", str(tmp_path / "data"), "--report-dir", str(tmp_path / "reports")],
                client=FDAClient(session=Session(responses))) == 2
    assert not list(tmp_path.rglob("*.complete"))
    assert not list(tmp_path.rglob("*.json"))


def test_b7_zip_symlink_and_bomb_rejected():
    from app.sources.regulatory import validation
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        link = zipfile.ZipInfo("link.json")
        link.create_system = 3
        link.external_attr = (0o120777 << 16)
        z.writestr(link, b"{}")
    with pytest.raises(RegulatoryError) as error:
        extract_zip(out.getvalue())
    assert error.value.code == "invalid_zip"
    with pytest.raises(RegulatoryError) as error:
        extract_zip(archive({"results": "x" * 100_000}))
    assert error.value.code == "invalid_zip"


def test_b7_interrupted_query_no_artifact(tmp_path):
    class Interrupted(Response):
        def iter_content(self, chunk_size):
            import requests
            yield b'{"meta":'
            raise requests.ConnectionError("test interruption")
    assert main(["--source", "fda-drugsfda", "--query", "x", "--save",
                 "--data-dir", str(tmp_path / "data"), "--report-dir", str(tmp_path / "reports")],
                client=FDAClient(session=Session([Interrupted(b"")]), api_key="LOCAL_TEST_ONLY")) == 2
    assert not list(tmp_path.rglob("*.complete"))


@pytest.mark.parametrize("invalid", [True, None, "2", -1])
def test_b7_bulk_partition_envelope_count_type_fails_closed(invalid):
    manifest, zipped, _ = bulk_input()
    body = source()
    body["meta"]["results"]["total"] = invalid
    with pytest.raises(RegulatoryError) as error:
        FDAClient(session=Session([Response(payload(manifest)), Response(archive(body))])).bulk()
    assert error.value.code == "incomplete_ingestion"


def test_b7_two_partitions_complete_and_source_locators(tmp_path):
    manifest, _, url = bulk_input()
    url2 = url.replace("0001-of-0001", "0002-of-0002")
    data = source()
    first, second = data["results"]
    manifest["results"]["drug"]["drugsfda"]["partitions"] = [
        {"file": url, "records": 1}, {"file": url2, "records": 1}]
    def part(row):
        result = copy.deepcopy(data)
        result["results"] = [row]
        result["meta"]["results"].update(total=1, limit=1)
        return archive(result)
    session = Session([Response(payload(manifest)), Response(part(first)), Response(part(second))])
    snapshot = FDAClient(session=session).bulk(retrieved_at="2026-09-26T00:00:00Z")
    assert snapshot["retrieval"]["partition_count"] == 2
    assert snapshot["retrieval"]["source_total"] == 2
    assert [r["provenance"]["source_record_locator"] for r in snapshot["records"]] == [
        url + "#results[0]", url2 + "#results[0]"]
    assert all("accessdata.fda.gov" not in call[0] for call in session.calls)
    from app.services.regulatory_persistence import save_snapshot, load_snapshot
    saved = save_snapshot(snapshot, tmp_path / "data", tmp_path / "reports", "two")
    assert load_snapshot(saved[0]) == snapshot


def test_b7_checksummed_bulk_fixture_roundtrip(tmp_path):
    from pathlib import Path
    import hashlib
    from tests.test_b7_regulatory import FIX
    from app.services.regulatory_persistence import save_snapshot, load_snapshot
    expected = json.loads((FIX / "manifest.json").read_text(encoding="utf-8"))
    for name in ("bulk_manifest.json", "bulk_partition.json.zip"):
        assert hashlib.sha256((FIX / name).read_bytes()).hexdigest() == expected["checksums"][name]
    source_manifest = (FIX / "bulk_manifest.json").read_bytes()
    source_zip = (FIX / "bulk_partition.json.zip").read_bytes()
    client = FDAClient(session=Session([Response(source_manifest), Response(source_zip)]))
    observation = client.bulk(retrieved_at="2026-09-26T00:00:00Z")
    assert [r["source_document_id"] for r in observation["records"]] == expected["record_ids"]
    assert observation["retrieval"]["source_total"] == expected["record_count"]
    saved = save_snapshot(observation, tmp_path / "data", tmp_path / "reports", "bulk_fixture")
    assert load_snapshot(saved[0]) == observation


def test_b7_inconsistent_partition_metadata_no_publish(tmp_path):
    manifest, _, url = bulk_input()
    url2 = url.replace("0001-of-0001", "0002-of-0002")
    manifest["results"]["drug"]["drugsfda"]["partitions"] = [
        {"file": url, "records": 1}, {"file": url2, "records": 1}]
    data = source()
    one, two = data["results"]
    def part(row, altered):
        result = copy.deepcopy(data)
        result["results"] = [row]
        result["meta"]["results"].update(total=1, limit=1)
        if altered:
            result["meta"]["disclaimer"] = "inconsistent"
        return Response(archive(result))
    assert main(["--source", "fda-drugsfda", "--manifest", "--save",
                 "--data-dir", str(tmp_path / "data"), "--report-dir", str(tmp_path / "reports")],
                client=FDAClient(session=Session([Response(payload(manifest)), part(one, False), part(two, True)]))) == 2
    assert not list(tmp_path.rglob("*.complete"))


def test_b7_json_depth_and_object_count_bounds(monkeypatch):
    from app.sources.regulatory import validation
    monkeypatch.setattr(validation, "MAX_JSON_NODES", 100_000)
    parse_json = validation.parse_json
    for content in (b"[" * 101 + b"0" + b"]" * 101,
                    b"[" + b"0," * 100_001 + b"0]"):
        with pytest.raises(RegulatoryError) as error:
            parse_json(content)
        assert error.value.code == "response_too_large"


def test_b7_invalid_partition_envelope_type_is_error_not_success():
    manifest, zipped, _ = bulk_input()
    body = source()
    body["meta"]["results"]["limit"] = True
    with pytest.raises(RegulatoryError) as error:
        FDAClient(session=Session([Response(payload(manifest)), Response(archive(body))])).bulk()
    assert error.value.code == "incomplete_ingestion"


def test_b7_boolean_one_record_partition_count_is_not_integer():
    manifest, _, _ = bulk_input()
    dataset = manifest["results"]["drug"]["drugsfda"]
    dataset["total_records"] = 1
    dataset["partitions"][0]["records"] = 1
    body = source()
    body["results"] = body["results"][:1]
    body["meta"]["results"].update(total=True, limit=1, skip=0)
    with pytest.raises(RegulatoryError) as error:
        FDAClient(session=Session([Response(payload(manifest)), Response(archive(body))])).bulk()
    assert error.value.code == "incomplete_ingestion"


def test_b7_reader_refuses_interrupted_and_modified_publications(tmp_path):
    from app.services.regulatory_normalizer import normalize_response
    from app.services.regulatory_persistence import load_published_snapshot, save_snapshot
    snapshot = normalize_response(source(), method="query", scope="x", retrieved_at="2026-09-26T00:00:00Z")
    data, reports = tmp_path / "data", tmp_path / "reports"
    data.mkdir()
    reports.mkdir()
    (data / "crashed.json").write_text(json.dumps(snapshot), encoding="utf-8")
    with pytest.raises(RegulatoryError) as exc:
        load_published_snapshot(data, reports, "crashed")
    assert exc.value.code == "artifact_corrupt"
    paths = save_snapshot(snapshot, data, reports, "valid")
    assert load_published_snapshot(data, reports, "valid") == snapshot
    paths[1].write_text("tampered", encoding="utf-8")
    with pytest.raises(RegulatoryError) as exc:
        load_published_snapshot(data, reports, "valid")
    assert exc.value.code == "artifact_corrupt"


def test_b7_total_elapsed_deadline_rejects_slow_stream(monkeypatch):
    from app.sources.regulatory import fda_openfda
    times = iter((0.0, 1.0, 1000.0))
    monkeypatch.setattr(fda_openfda.time, "monotonic", lambda: next(times))
    with pytest.raises(RegulatoryError) as exc:
        FDAClient(session=Session([Response(payload(source()))]), api_key="LOCAL_TEST_ONLY").query("x", limit=2)
    assert exc.value.code == "source_unavailable"


def test_b7_additional_credential_aliases_and_multi_member_archives_fail_closed():
    from app.sources.regulatory.validation import source_link
    for url in ("https://example.test/a?client_secret=LEAK", "https://example.test/a?sig=LEAK",
                "https://example.test/a?access-token=LEAK"):
        with pytest.raises(RegulatoryError) as exc:
            source_link(url)
        assert exc.value.code == "malformed_source"
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive_file:
        archive_file.writestr("one.json", b"{}")
        archive_file.writestr("two.json", b"{}")
    with pytest.raises(RegulatoryError) as exc:
        extract_zip(out.getvalue())
    assert exc.value.code == "invalid_zip"


def test_b7_completion_marker_last_and_recovery_after_interrupted_marker(tmp_path, monkeypatch):
    from app.services import regulatory_persistence as storage
    from app.services.regulatory_normalizer import normalize_response
    snapshot = normalize_response(source(), method="query", scope="x", retrieved_at="2026-09-26T00:00:00Z")
    original = storage.os.replace
    calls = []
    def stop_before_marker(src, dst):
        calls.append(dst.name)
        if dst.name.endswith(".complete"):
            raise OSError("simulated interruption")
        return original(src, dst)
    monkeypatch.setattr(storage.os, "replace", stop_before_marker)
    with pytest.raises(RegulatoryError) as exc:
        storage.save_snapshot(snapshot, tmp_path / "data", tmp_path / "reports", "recover")
    assert exc.value.code == "artifact_write_failed"
    assert calls[-1] == "recover.complete"
    assert not list(tmp_path.rglob("recover.*"))
    monkeypatch.setattr(storage.os, "replace", original)
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "reports").mkdir(exist_ok=True)
    (tmp_path / "data" / "recover.json").write_text("partial", encoding="utf-8")
    (tmp_path / "reports" / "recover.md").write_text("partial", encoding="utf-8")
    with pytest.raises(RegulatoryError) as exc:
        storage.load_published_snapshot(tmp_path / "data", tmp_path / "reports", "recover")
    assert exc.value.code == "artifact_corrupt"
    saved = storage.save_snapshot(snapshot, tmp_path / "data", tmp_path / "reports", "recover")
    assert storage.load_published_snapshot(tmp_path / "data", tmp_path / "reports", "recover") == snapshot
    assert saved[-1].exists()