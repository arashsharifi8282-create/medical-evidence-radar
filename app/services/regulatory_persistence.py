"""Independent b7/1.0 audit and safe human-readable projections."""
from __future__ import annotations

import html
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from app.services.regulatory_normalizer import digest
from app.sources.regulatory.validation import API_URL, MANIFEST_URL, RegulatoryError, require, utc_date, dataset_date, source_date, safe_query_scope, safe_url, parse_json


def _shape(value, keys):
    require(type(value) is dict and set(value) == set(keys.split()), "artifact_corrupt")


def _text(value, nullable=False):
    require((value is None and nullable) or type(value) is str, "artifact_corrupt")


def _hash(value, nullable=False):
    require((value is None and nullable) or
            (type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None), "artifact_corrupt")


def _fields(value, names):
    _shape(value, names)
    for key, item in value.items():
        _shape(item, "state path raw_value")
        require(item["state"] in ("absent", "null", "present") and type(item["path"]) is str and
                item["path"].endswith("." + key), "artifact_corrupt")
        require((item["state"] == "absent" and item["raw_value"] is None) or
                (item["state"] == "null" and item["raw_value"] is None) or
                (item["state"] == "present" and item["raw_value"] is not None), "artifact_corrupt")


def _path_fields(value, prefix):
    require(all(item["path"] == prefix + "." + key for key, item in value.items()), "artifact_corrupt")


def _mapped(value, entry, *, required=False, date_field=False):
    """Check recorded raw scalar against its persisted projection, not its authenticity."""
    raw = entry["raw_value"]
    if required:
        require(entry["state"] == "present" and type(raw) is str and bool(raw.strip()) and value == raw,
                "artifact_corrupt")
        return
    require(entry["state"] != "present" or type(raw) is str, "artifact_corrupt")
    try:
        expected = (source_date(raw) if date_field else raw or None) if entry["state"] == "present" else None
    except RegulatoryError:
        raise RegulatoryError("artifact_corrupt") from None
    require(value == expected, "artifact_corrupt")


def _indexed_path(path, parent, container, field):
    match = re.fullmatch(re.escape(parent + "." + container + "[") + r"(\d+)\]\." + re.escape(field), path)
    require(match is not None, "artifact_corrupt")
    return path[:-(len(field) + 1)]


def _semantic_record(row):
    identity = row["canonical_identity"]
    return {"identity": identity, "normalization_version": "1.0", "status_policy_version": "1.0",
            "sponsor_name": row["sponsor_name"], "publication_date": None,
            "document_status": "unknown", "needs_review": row["needs_review"],
            "review_reasons": row["review_reasons"],
            "products": [{**{k: v for k, v in p.items() if k not in ("source_fields", "active_ingredients")},
                          "active_ingredients": [{k: v for k, v in i.items() if k != "source_fields"}
                                                 for i in p["active_ingredients"]]} for p in row["products"]],
            "submissions": [{**{k: v for k, v in s.items() if k not in ("source_fields", "application_docs")},
                             "application_docs": [{k: v for k, v in d.items() if k != "source_fields"}
                                                  for d in s["application_docs"]]} for s in row["submissions"]]}


def _nested(row):
    require(type(row["products"]) is list and type(row["submissions"]) is list, "artifact_corrupt")
    product_ids, submission_ids = set(), set()
    root = row["provenance"]["source_record_locator"]
    for container, items in (("products", row["products"]), ("submissions", row["submissions"])):
        state = row["raw_field_state"][container]
        require(state == "present" or not items, "artifact_corrupt")
    require(row["raw_field_state"]["application_number"] == "present" and
            (row["sponsor_name"] is None or row["raw_field_state"]["sponsor_name"] == "present"),
            "artifact_corrupt")
    def check_container(entry, children, parent, container, marker):
        raw = entry["raw_value"]
        require((entry["state"] == "present" and type(raw) is list and len(raw) == len(children)) or
                (entry["state"] != "present" and raw is None and not children), "artifact_corrupt")
        seen = set()
        for child in children:
            path = _indexed_path(child["source_fields"][marker]["path"], parent, container, marker)
            match = re.fullmatch(re.escape(parent + "." + container + "[") + r"(\d+)\]", path)
            require(match is not None, "artifact_corrupt")
            index = int(match.group(1))
            require(index < len(raw) and index not in seen and type(raw[index]) is dict, "artifact_corrupt")
            seen.add(index)
            for key, field in child["source_fields"].items():
                original = raw[index]
                state = "absent" if key not in original else "null" if original[key] is None else "present"
                require(field["state"] == state and field["raw_value"] == original.get(key), "artifact_corrupt")
    for product in row["products"]:
        _shape(product, "product_number brand_name marketing_status dosage_form route active_ingredients source_fields")
        _fields(product["source_fields"], "product_number brand_name marketing_status dosage_form route active_ingredients")
        ppath = _indexed_path(product["source_fields"]["product_number"]["path"], root, "products", "product_number")
        _path_fields(product["source_fields"], ppath)
        _text(product["product_number"])
        require(bool(product["product_number"].strip()) and product["product_number"] not in product_ids, "artifact_corrupt")
        product_ids.add(product["product_number"])
        _mapped(product["product_number"], product["source_fields"]["product_number"], required=True)
        for key in ("brand_name", "marketing_status", "dosage_form", "route"):
            _text(product[key], True)
            _mapped(product[key], product["source_fields"][key])
        require(type(product["active_ingredients"]) is list, "artifact_corrupt")
        check_container(product["source_fields"]["active_ingredients"], product["active_ingredients"], ppath, "active_ingredients", "name")
        for ingredient in product["active_ingredients"]:
            _shape(ingredient, "name strength source_fields")
            _fields(ingredient["source_fields"], "name strength")
            ipath = _indexed_path(ingredient["source_fields"]["name"]["path"], ppath, "active_ingredients", "name")
            _path_fields(ingredient["source_fields"], ipath)
            for key in ("name", "strength"):
                _text(ingredient[key], True)
                _mapped(ingredient[key], ingredient["source_fields"][key])
    for submission in row["submissions"]:
        _shape(submission, "submission_type submission_number submission_status submission_status_date application_docs source_fields")
        _fields(submission["source_fields"], "submission_type submission_number submission_status submission_status_date application_docs")
        spath = _indexed_path(submission["source_fields"]["submission_type"]["path"], root, "submissions", "submission_type")
        _path_fields(submission["source_fields"], spath)
        pair = (submission["submission_type"], submission["submission_number"])
        require(all(type(x) is str and bool(x.strip()) for x in pair) and pair not in submission_ids, "artifact_corrupt")
        submission_ids.add(pair)
        for key in ("submission_type", "submission_number"):
            _mapped(submission[key], submission["source_fields"][key], required=True)
        _text(submission["submission_status"], True)
        _mapped(submission["submission_status"], submission["source_fields"]["submission_status"])
        _iso_date(submission["submission_status_date"])
        _mapped(submission["submission_status_date"], submission["source_fields"]["submission_status_date"], date_field=True)
        require(type(submission["application_docs"]) is list, "artifact_corrupt")
        check_container(submission["source_fields"]["application_docs"], submission["application_docs"], spath, "application_docs", "id")
        for link in submission["application_docs"]:
            _shape(link, "id date title type url source_fields")
            _fields(link["source_fields"], "id date title type url")
            lpath = _indexed_path(link["source_fields"]["id"]["path"], spath, "application_docs", "id")
            _path_fields(link["source_fields"], lpath)
            _iso_date(link["date"])
            _mapped(link["date"], link["source_fields"]["date"], date_field=True)
            for key in ("id", "title", "type", "url"):
                _text(link[key], True)
                _mapped(link[key], link["source_fields"][key])


def _iso_date(value):
    require(value is None or (type(value) is str and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)), "artifact_corrupt")
    if value is not None:
        try:
            dataset_date(value)
        except RegulatoryError:
            raise RegulatoryError("artifact_corrupt") from None


def validate_snapshot(snapshot):
    require(type(snapshot) is dict, "artifact_corrupt")
    require(snapshot.get("schema_version") == "b7/1.0" and
            all(snapshot.get(k) == "1.0" for k in ("normalization_version", "identity_policy_version",
                 "version_policy_version", "status_policy_version")), "unsupported_schema_version")
    _shape(snapshot, "schema_version source_authority source_system document_type jurisdiction normalization_version identity_policy_version version_policy_version status_policy_version retrieval records audit")
    require(snapshot.get("source_authority") == "FDA" and snapshot.get("source_system") == "openFDA" and
            snapshot.get("jurisdiction") == "US" and snapshot.get("document_type") == "drug_application", "artifact_corrupt")
    retrieval = snapshot.get("retrieval")
    audit = snapshot.get("audit")
    rows = snapshot.get("records")
    _shape(retrieval, "method source_url query retrieved_at dataset_timestamp dataset_timestamp_kind completeness source_total observed_count partition_count partition_digests source_disclaimer source_terms_url source_license_url raw_response_sha256")
    _shape(audit, "warnings record_count source_field_coverage snapshot_semantic_sha256")
    require(type(rows) is list and type(audit["record_count"]) is int and
            type(retrieval["observed_count"]) is int and
            audit.get("record_count") == len(rows) and retrieval.get("observed_count") == len(rows) and
            retrieval.get("completeness") in ("bounded_query", "complete_bulk"), "artifact_corrupt")
    try:
        utc_date(retrieval["retrieved_at"])
    except RegulatoryError:
        raise RegulatoryError("artifact_corrupt") from None
    require(retrieval["method"] in ("query", "bulk") and
            retrieval["source_url"] == (API_URL if retrieval["method"] == "query" else MANIFEST_URL) and
            retrieval["completeness"] == ("bounded_query" if retrieval["method"] == "query" else "complete_bulk") and
            type(retrieval["source_total"]) is int and retrieval["source_total"] >= len(rows) and
            type(retrieval["partition_digests"]) is list, "artifact_corrupt")
    _iso_date(retrieval["dataset_timestamp"])
    require(retrieval["dataset_timestamp_kind"] == ("unavailable" if retrieval["dataset_timestamp"] is None else
            "meta.last_updated" if retrieval["method"] == "query" else "export_date"), "artifact_corrupt")
    for key in ("source_disclaimer", "source_terms_url", "source_license_url"):
        _text(retrieval[key], True)
    _hash(retrieval["raw_response_sha256"], True)
    require(type(audit["warnings"]) is list and all(type(x) is str for x in audit["warnings"]) and
            any("not retained" in warning for warning in audit["warnings"]) and type(audit["source_field_coverage"]) is dict and
            not audit["source_field_coverage"], "artifact_corrupt")
    _hash(audit["snapshot_semantic_sha256"])
    if retrieval["method"] == "query":
        try:
            safe_query_scope(retrieval["query"])
        except RegulatoryError:
            raise RegulatoryError("artifact_corrupt") from None
        require(retrieval["partition_count"] is None and not retrieval["partition_digests"], "artifact_corrupt")
    else:
        require(retrieval["query"] is None and type(retrieval["partition_count"]) is int and
                retrieval["partition_count"] == len(retrieval["partition_digests"]) and
                retrieval["partition_count"] > 0 and retrieval["source_total"] == len(rows), "artifact_corrupt")
    for part in retrieval["partition_digests"]:
        _shape(part, "url sha256")
        try:
            safe_url(part["url"], partition=True)
        except RegulatoryError:
            raise RegulatoryError("artifact_corrupt") from None
        _hash(part["sha256"])
    ids = []
    for row in rows:
        _shape(row, "source_document_id canonical_identity title sponsor_name publication_date canonical_url document_status needs_review review_reasons products submissions raw_field_state provenance raw_source_reference content_digest")
        require(type(row) is dict and type(row.get("source_document_id")) is str and
                bool(row["source_document_id"].strip()) and row.get("document_status") == "unknown" and
                row["title"] is None and row["publication_date"] is None and row["canonical_url"] == API_URL and
                type(row["needs_review"]) is bool and type(row["review_reasons"]) is list and
                all(type(reason) is str for reason in row["review_reasons"]) and
                row["review_reasons"] == sorted(set(row["review_reasons"])) and
                row["needs_review"] == bool(row["review_reasons"]) and
                type(row.get("provenance")) is dict and type(row.get("raw_source_reference")) is dict and
                type(row.get("content_digest")) is str and
                bool(re.fullmatch(r"[0-9a-f]{64}", row["content_digest"])), "artifact_corrupt")
        _text(row["sponsor_name"], True)
        _shape(row["canonical_identity"], "source_authority document_type source_document_id")
        require(row["canonical_identity"] == {"source_authority": "FDA", "document_type": "drug_application",
                "source_document_id": row["source_document_id"]}, "artifact_corrupt")
        _shape(row["raw_field_state"], "application_number sponsor_name products submissions openfda")
        require(all(x in ("absent", "null", "present") for x in row["raw_field_state"].values()) and
                row["raw_field_state"]["application_number"] == "present" and
                ((row["sponsor_name"] is None) or row["raw_field_state"]["sponsor_name"] == "present") and
                ((not row["products"]) or row["raw_field_state"]["products"] == "present") and
                ((not row["submissions"]) or row["raw_field_state"]["submissions"] == "present"), "artifact_corrupt")
        _shape(row["provenance"], "source_authority source_system jurisdiction document_type source_document_id source_url source_record_locator source_record_sha256 retrieval_method dataset_timestamp normalization_version identity_policy_version version_policy_version status_policy_version license_note field_paths")
        provenance = row["provenance"]
        require(type(provenance["source_record_locator"]) is str, "artifact_corrupt")
        require(all(provenance[k] == snapshot[k] for k in ("source_authority", "source_system", "jurisdiction", "document_type", "normalization_version", "identity_policy_version", "version_policy_version", "status_policy_version")) and
                provenance["source_document_id"] == row["source_document_id"] and
                provenance["source_url"] == API_URL and provenance["retrieval_method"] == retrieval["method"] and
                provenance["dataset_timestamp"] == retrieval["dataset_timestamp"] and
                type(provenance["license_note"]) is str, "artifact_corrupt")
        _shape(provenance["field_paths"], "source_document_id sponsor_name document_status")
        require(all(type(p) is str for p in provenance["field_paths"].values()) and
                provenance["field_paths"]["document_status"] == "FDA_APPLICATION_STATUS_UNMAPPED/1.0" and
                provenance["field_paths"]["source_document_id"] == provenance["source_record_locator"] + ".application_number" and
                provenance["field_paths"]["sponsor_name"] == provenance["source_record_locator"] + ".sponsor_name", "artifact_corrupt")
        _shape(row["raw_source_reference"], "response_sha256 record_sha256 locator")
        reference = row["raw_source_reference"]
        _hash(provenance["source_record_sha256"])
        _hash(reference["record_sha256"])
        _hash(reference["response_sha256"], True)
        require(reference["record_sha256"] == provenance["source_record_sha256"] and
                reference["response_sha256"] == retrieval["raw_response_sha256"] and
                type(reference["locator"]) is str and reference["locator"] == provenance["source_record_locator"], "artifact_corrupt")
        _nested(row)
        require(row["content_digest"] == digest(_semantic_record(row)), "artifact_corrupt")
        ids.append(row["source_document_id"])
    require(len(set(ids)) == len(ids), "duplicate_document_id")
    require(ids == sorted(ids), "artifact_corrupt")
    expected = digest({"schema_version": "b7/1.0", "policies": ("1.0",) * 4,
                       "method": retrieval["method"], "scope": retrieval["query"],
                       "records": [(r["canonical_identity"], r["content_digest"]) for r in rows]})
    require(audit["snapshot_semantic_sha256"] == expected, "artifact_corrupt")
    return snapshot


def canonical_json(snapshot):
    validate_snapshot(snapshot)
    return json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"


def load_snapshot(path):
    try:
        return validate_snapshot(parse_json(Path(path).read_bytes()))
    except RegulatoryError as error:
        if error.code in ("invalid_json", "response_too_large"):
            raise RegulatoryError("artifact_corrupt") from None
        raise
    except (ValueError, OSError, UnicodeError, TypeError):
        raise RegulatoryError("artifact_corrupt") from None


def _escape(value):
    text = "" if value is None else str(value)
    text = text.replace("\\", "\\\\").replace("\r", "&#13;").replace("\n", "&#10;")
    for character in ("`", "*", "_", "[", "]", "#", "!", "~"):
        text = text.replace(character, "\\" + character)
    return html.escape(text, quote=True).replace("|", "&#124;")


def render_markdown(snapshot):
    validate_snapshot(snapshot)
    info = snapshot["retrieval"]
    lines = ["# FDA Drugs@FDA application metadata observation", "",
             "Research metadata only; not clinical advice or a regulatory determination.",
             "Data provided by the U.S. Food and Drug Administration (openFDA).",
             "", f"- Jurisdiction: {_escape(snapshot['jurisdiction'])}",
             f"- Retrieval: {_escape(info['method'])}; {_escape(info['completeness'])}",
             f"- Retrieved at (UTC): {_escape(info['retrieved_at'])}",
             f"- Dataset timestamp: {_escape(info['dataset_timestamp'])} ({_escape(info['dataset_timestamp_kind'])})",
             f"- Scope: {_escape(info['query'])}",
             f"- Records: {len(snapshot['records'])}",
             f"- Semantic SHA-256: {_escape(snapshot['audit']['snapshot_semantic_sha256'])}",
             f"- Source disclaimer: {_escape(info['source_disclaimer'])}",
             f"- Source terms URL (text only): {_escape(info['source_terms_url'])}",
             f"- Source license URL (text only): {_escape(info['source_license_url'])}",
             f"- Raw response/manifest SHA-256: {_escape(info['raw_response_sha256'])}",
             "- License: openFDA metadata generally CC0; linked documents may have third-party rights. No PDFs retrieved.", ""]
    for row in snapshot["records"]:
        lines.extend([f"## Application {_escape(row['source_document_id'])}",
            f"- Sponsor (source): {_escape(row['sponsor_name'])}",
            "- Application-wide status: unknown (not assessed)",
            f"- Products: {len(row['products'])}; submissions: {len(row['submissions'])}",
            f"- Record SHA-256: {_escape(row['raw_source_reference']['record_sha256'])}"])
        for p in row["products"]:
            lines.append(f"- Product {_escape(p['product_number'])}: {_escape(p['brand_name'])}; marketing_status (product only): {_escape(p['marketing_status'])}")
        for s in row["submissions"]:
            lines.append(f"- Submission {_escape(s['submission_type'])} {_escape(s['submission_number'])}: source status {_escape(s['submission_status'])}; date {_escape(s['submission_status_date'])}; document links (metadata only): {len(s['application_docs'])}")
            for link in s["application_docs"]:
                lines.append("  - Document link metadata (text only): " + "; ".join(
                    f"{key}: {_escape(link[key])}" for key in ("id", "date", "title", "type", "url")))
        lines.append("")
    return "\n".join(lines) + "\n"


def render_html(snapshot):
    validate_snapshot(snapshot)
    info = snapshot["retrieval"]
    out = ['<!doctype html><html lang="en"><head><meta charset="utf-8"><title>FDA metadata observation</title></head><body>',
           '<h1>FDA Drugs@FDA application metadata observation</h1>',
           '<p>Research metadata only; not clinical advice or a regulatory determination. Data provided by the U.S. Food and Drug Administration (openFDA). No PDFs retrieved.</p>',
           f'<p>Records: {len(snapshot["records"])}; Retrieval: {_escape(info["method"])}; {_escape(info["completeness"])}; Retrieved at (UTC): {_escape(info["retrieved_at"])}; Dataset timestamp: {_escape(info["dataset_timestamp"])} ({_escape(info["dataset_timestamp_kind"])}); Scope: {_escape(info["query"])}; Semantic SHA-256: {_escape(snapshot["audit"]["snapshot_semantic_sha256"])}; Source disclaimer: {_escape(info["source_disclaimer"])}; Source terms URL (text only): {_escape(info["source_terms_url"])}; Source license URL (text only): {_escape(info["source_license_url"])}; Raw response/manifest SHA-256: {_escape(info["raw_response_sha256"])}.</p>']
    for row in snapshot["records"]:
        out.append(f'<article><h2>## Application {_escape(row["source_document_id"])}</h2><p>Sponsor (source): {_escape(row["sponsor_name"])}; Application-wide status: unknown (not assessed); Products: {len(row["products"])}; submissions: {len(row["submissions"])}; Record SHA-256: {_escape(row["raw_source_reference"]["record_sha256"])}.</p>')
        for product in row["products"]:
            out.append(f'<section><h3>Product {_escape(product["product_number"])}</h3><p>Brand (source): {_escape(product["brand_name"])}; marketing_status (product only): {_escape(product["marketing_status"])}; dosage_form: {_escape(product["dosage_form"])}; route: {_escape(product["route"])}.</p></section>')
        for submission in row["submissions"]:
            out.append(f'<section><h3>Submission {_escape(submission["submission_type"])} {_escape(submission["submission_number"])}</h3><p>source status {_escape(submission["submission_status"])}; date {_escape(submission["submission_status_date"])}; document links (metadata only): {len(submission["application_docs"])}.</p>')
            for link in submission["application_docs"]:
                out.append('<p>Document link metadata (text only): ' + '; '.join(
                    f'{key}: {_escape(link[key])}' for key in ("id", "date", "title", "type", "url")) + '</p>')
            out.append('</section>')
        out.append('</article>')
    return ''.join(out) + '</body></html>\n'


def save_snapshot(snapshot, data_dir: Path, report_dir: Path, name: str):
    require(type(name) is str and bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", name)), "invalid_scope")
    payloads = (canonical_json(snapshot), render_markdown(snapshot), render_html(snapshot))
    data_dir, report_dir = Path(data_dir), Path(report_dir)
    paths = (data_dir / f"{name}.json", report_dir / f"{name}.md", report_dir / f"{name}.html",
             report_dir / f"{name}.complete")
    _recover_incomplete(paths)
    require(not any(path.exists() for path in paths), "artifact_write_failed")
    temporary = []
    published = []
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        report_dir.mkdir(parents=True, exist_ok=True)
        encoded = [text.encode("utf-8") for text in payloads]
        marker = (json.dumps({"schema_version": "b7-completion/1.0", "files": {
            path.name: hashlib.sha256(content).hexdigest() for path, content in zip(paths[:3], encoded)
        }}, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        for path, content in zip(paths, (*encoded, marker)):
            with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent,
                                             prefix=".b7-", delete=False) as stream:
                temporary.append(Path(stream.name))
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        # Verify the serialized audit before any artifact is published.
        load_snapshot(temporary[0])
        for path, tmp in zip(paths[:3], temporary[:3]):
            require(not path.exists(), "artifact_write_failed")
            os.replace(tmp, path)
            published.append(path)
        for directory in {data_dir, report_dir}:
            _sync_directory(directory)
        require(all(path.read_bytes() == content for path, content in zip(paths[:3], encoded)),
                "artifact_write_failed")
        require(not paths[3].exists(), "artifact_write_failed")
        os.replace(temporary[3], paths[3])
        published.append(paths[3])
        _sync_directory(report_dir)
        return paths
    except (OSError, ValueError, RegulatoryError) as error:
        for path in temporary + published:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        if isinstance(error, RegulatoryError):
            raise
        raise RegulatoryError("artifact_write_failed") from None


def _recover_incomplete(paths):
    """Discard only an unpublished, marker-less generation left by a process crash."""
    marker = paths[3]
    if marker.exists():
        return
    for path in paths[:3]:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            raise RegulatoryError("artifact_write_failed") from None


def _sync_directory(directory):
    """Directory fsync where supported; Windows replace is atomic but directory fsync unavailable."""
    if os.name != "nt":
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def load_published_snapshot(data_dir: Path, report_dir: Path, name: str):
    """Only accept a completed generation whose JSON and projections match its marker."""
    require(type(name) is str and bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", name)), "invalid_scope")
    paths = (Path(data_dir) / f"{name}.json", Path(report_dir) / f"{name}.md",
             Path(report_dir) / f"{name}.html")
    marker = Path(report_dir) / f"{name}.complete"
    try:
        manifest = parse_json(marker.read_bytes())
        _shape(manifest, "schema_version files")
        require(manifest["schema_version"] == "b7-completion/1.0", "artifact_corrupt")
        _shape(manifest["files"], " ".join(p.name for p in paths))
        contents = [p.read_bytes() for p in paths]
        for path, content in zip(paths, contents):
            require(hashlib.sha256(content).hexdigest() == manifest["files"][path.name], "artifact_corrupt")
        snapshot = validate_snapshot(parse_json(contents[0]))
        require(contents[1] == render_markdown(snapshot).encode("utf-8") and
                contents[2] == render_html(snapshot).encode("utf-8"), "artifact_corrupt")
        return snapshot
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, RegulatoryError):
        raise RegulatoryError("artifact_corrupt") from None