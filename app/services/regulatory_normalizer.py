"""Pure deterministic projection of validated Drugs@FDA observations."""
from __future__ import annotations

import hashlib
import json

from app.sources.regulatory.validation import (API_URL, RegulatoryError, array_value,
    dataset_date, nested_id, object_value, optional_date, require, source_link, source_text, utc_date)

SCHEMA = "b7/1.0"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def fields(obj, names, path):
    return {k: {"state": "absent" if k not in obj else "null" if obj[k] is None else "present",
                "path": f"{path}.{k}", "raw_value": obj.get(k)} for k in names}


def optional(obj, name):
    value = obj.get(name)
    value = source_text(value) if value is not None else None
    return None if value == "" else value


def normalize_response(response: dict, *, method: str, scope: str | None,
                       retrieved_at: str, raw_bytes: bytes | None = None,
                       dataset_timestamp: str | None = None,
                       locator: str = "results", record_locators: list[str] | None = None,
                       partition_digests: list | None = None,
                       source_total: int | None = None) -> dict:
    require(method in ("query", "bulk") and (method != "query" or
            type(scope) is str and bool(scope.strip())), "invalid_scope")
    utc_date(retrieved_at)
    root = object_value(response)
    meta = object_value(root.get("meta"))
    counts = object_value(meta.get("results"))
    results = array_value(root.get("results"))
    require(record_locators is None or
            (type(record_locators) is list and len(record_locators) == len(results) and
             all(type(x) is str for x in record_locators)), "malformed_source")
    for key in ("total", "limit", "skip"):
        require(type(counts.get(key)) is int and counts[key] >= 0, "malformed_source")
    require(counts["limit"] >= len(results) and counts["total"] >= len(results), "incomplete_ingestion")
    if method == "query":
        require(counts["skip"] == 0, "invalid_scope")
        stamp = dataset_date(meta.get("last_updated"))
        kind = "meta.last_updated" if stamp else "unavailable"
    else:
        stamp = dataset_date(dataset_timestamp)
        kind = "export_date" if stamp else "unavailable"
        require(source_total is not None and type(source_total) is int and len(results) == source_total,
                "incomplete_ingestion")
    documents = []
    used = set()
    require(type(meta.get("disclaimer")) is str and bool(meta["disclaimer"]), "malformed_source")
    require(type(meta.get("terms")) is str and type(meta.get("license")) is str,
            "malformed_source")
    for index, raw in enumerate(results):
        record = object_value(raw)
        identifier = source_text(record.get("application_number"), required=True, identifier=True)
        require(identifier not in used, "duplicate_document_id")
        used.add(identifier)
        path = record_locators[index] if record_locators is not None else f"{locator}[{index}]"
        products = []
        product_ids = set()
        for j, value in enumerate(array_value(record.get("products", []))):
            item = object_value(value)
            number = nested_id(item.get("product_number"))
            require(number not in product_ids, "duplicate_nested_id")
            product_ids.add(number)
            ingredients = []
            for k, ingredient in enumerate(array_value(item.get("active_ingredients", []))):
                source = object_value(ingredient)
                ingredients.append({"name": optional(source, "name"), "strength": optional(source, "strength"),
                                    "source_fields": fields(source, ("name", "strength"),
                                        f"{path}.products[{j}].active_ingredients[{k}]")})
            products.append({"product_number": number, "brand_name": optional(item, "brand_name"),
                             "marketing_status": optional(item, "marketing_status"),
                             "dosage_form": optional(item, "dosage_form"), "route": optional(item, "route"),
                              "active_ingredients": sorted(ingredients, key=lambda i: canonical({
                                  k: v for k, v in i.items() if k != "source_fields"})),
                             "source_fields": fields(item, ("product_number", "brand_name", "marketing_status",
                                "dosage_form", "route", "active_ingredients"), f"{path}.products[{j}]")})
        submissions = []
        submission_ids = set()
        for j, value in enumerate(array_value(record.get("submissions", []))):
            item = object_value(value)
            kind_id = nested_id(item.get("submission_type"))
            number = nested_id(item.get("submission_number"))
            require((kind_id, number) not in submission_ids, "duplicate_nested_id")
            submission_ids.add((kind_id, number))
            links = []
            for k, value in enumerate(array_value(item.get("application_docs", []))):
                doc = object_value(value)
                links.append({"id": optional(doc, "id"), "date": optional_date(doc, "date"),
                              "title": optional(doc, "title"), "type": optional(doc, "type"),
                               "url": source_link(optional(doc, "url")),
                              "source_fields": fields(doc, ("id", "date", "title", "type", "url"),
                                                      f"{path}.submissions[{j}].application_docs[{k}]")})
            submissions.append({"submission_type": kind_id, "submission_number": number,
                                "submission_status": optional(item, "submission_status"),
                                "submission_status_date": optional_date(item, "submission_status_date"),
                                "application_docs": sorted(links, key=lambda x: canonical({k:v for k,v in x.items() if k != "source_fields"})),
                                "source_fields": fields(item, ("submission_type", "submission_number",
                                    "submission_status", "submission_status_date", "application_docs"),
                                    f"{path}.submissions[{j}]")})
        identity = {"source_authority": "FDA", "document_type": "drug_application", "source_document_id": identifier}
        reasons = []
        if any(type(record.get(k)) is str and record[k] == "" for k in ("sponsor_name",)):
            reasons.append("empty_optional_value")
        if any(p["marketing_status"] not in (None, "Prescription", "Discontinued", "None (Tentative Approval)", "Over-the-counter") for p in products):
            reasons.append("unknown_product_marketing_status")
        if any(s["submission_status"] not in (None, "AP", "TA") for s in submissions):
            reasons.append("unknown_submission_status")
        products.sort(key=lambda p: p["product_number"])
        submissions.sort(key=lambda s: (s["submission_type"], s["submission_number"]))
        for p in products:
            if any(p["source_fields"][k]["raw_value"] == "" for k in ("brand_name", "marketing_status", "dosage_form", "route")):
                reasons.append("empty_optional_value")
        for s in submissions:
            if s["source_fields"]["submission_status"]["raw_value"] == "":
                reasons.append("empty_optional_value")
        reasons = sorted(set(reasons))
        semantic = {"identity": identity, "normalization_version": "1.0", "status_policy_version": "1.0",
                    "sponsor_name": optional(record, "sponsor_name"), "publication_date": None,
                    "document_status": "unknown", "needs_review": bool(reasons), "review_reasons": reasons,
                    "products": [{**{k:v for k,v in p.items() if k not in ("source_fields", "active_ingredients")},
                        "active_ingredients": [{k:v for k,v in i.items() if k != "source_fields"}
                                                for i in p["active_ingredients"]]} for p in products],
                    "submissions": [{**{k:v for k,v in s.items() if k not in ("source_fields", "application_docs")},
                        "application_docs": [{k:v for k,v in d.items() if k != "source_fields"} for d in s["application_docs"]]} for s in submissions]}
        raw_digest = digest(record)
        documents.append({"source_document_id": identifier, "canonical_identity": identity,
            "title": None, "sponsor_name": semantic["sponsor_name"], "publication_date": None,
            "canonical_url": API_URL, "document_status": "unknown", "needs_review": bool(reasons),
            "review_reasons": reasons, "products": products, "submissions": submissions,
            "raw_field_state": {k: "absent" if k not in record else "null" if record[k] is None else "present"
                                for k in ("application_number", "sponsor_name", "products", "submissions", "openfda")},
            "provenance": {"source_authority": "FDA", "source_system": "openFDA", "jurisdiction": "US",
                "document_type": "drug_application", "license_note": "openFDA metadata generally CC0; linked documents may have third-party rights; no PDFs retrieved",
                "source_document_id": identifier, "source_url": API_URL, "source_record_locator": path,
                "source_record_sha256": raw_digest, "retrieval_method": method,
                "dataset_timestamp": stamp, "normalization_version": "1.0", "identity_policy_version": "1.0",
                "version_policy_version": "1.0", "status_policy_version": "1.0",
                "field_paths": {"source_document_id": f"{path}.application_number",
                                "sponsor_name": f"{path}.sponsor_name", "document_status": "FDA_APPLICATION_STATUS_UNMAPPED/1.0"}},
            "raw_source_reference": {"response_sha256": hashlib.sha256(raw_bytes).hexdigest() if raw_bytes is not None else None,
                                     "record_sha256": raw_digest, "locator": path},
            "content_digest": digest(semantic)})
    documents.sort(key=lambda r: r["source_document_id"])
    semantic_id = digest({"schema_version": SCHEMA, "policies": ("1.0",) * 4,
                          "method": method, "scope": scope,
                          "records": [(r["canonical_identity"], r["content_digest"]) for r in documents]})
    disclaimer = source_text(meta.get("disclaimer"))
    terms = source_link(source_text(meta.get("terms")))
    license_url = source_link(source_text(meta.get("license")))
    return {"schema_version": SCHEMA, "source_authority": "FDA", "source_system": "openFDA",
            "document_type": "drug_application", "jurisdiction": "US",
            "normalization_version": "1.0", "identity_policy_version": "1.0",
            "version_policy_version": "1.0", "status_policy_version": "1.0",
            "retrieval": {"method": method, "source_url": API_URL if method == "query" else "https://api.fda.gov/download.json",
                "query": scope, "retrieved_at": retrieved_at, "dataset_timestamp": stamp,
                "dataset_timestamp_kind": kind, "completeness": "bounded_query" if method == "query" else "complete_bulk",
                "source_total": counts["total"] if method == "query" else source_total,
                "observed_count": len(documents), "partition_count": len(partition_digests or []) if method == "bulk" else None,
                "partition_digests": partition_digests or [], "source_disclaimer": disclaimer,
                "source_terms_url": terms, "source_license_url": license_url,
                "raw_response_sha256": hashlib.sha256(raw_bytes).hexdigest() if raw_bytes is not None else None},
            "records": documents,
            "audit": {"warnings": ["Raw record bytes are not retained in this snapshot; unknown fields are represented only by raw record digests."],
                "record_count": len(documents),
                "source_field_coverage": {}, "snapshot_semantic_sha256": semantic_id}}