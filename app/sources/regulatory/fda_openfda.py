"""Bounded, explicit FDA metadata retrieval; never visits linked documents."""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests

from app.services.regulatory_normalizer import normalize_response
from app.sources.regulatory.validation import (API_URL, MANIFEST_URL, MAX_RESPONSE,
    RegulatoryError, array_value, dataset_date, extract_zip, object_value,
    parse_json, require, safe_query_scope, safe_url)


class FDAClient:
    def __init__(self, session: requests.Session | None = None, api_key: str | None = None):
        self.session = session if session is not None else requests.Session()
        self.api_key = api_key if api_key is not None else os.environ.get("OPENFDA_API_KEY")

    def _get(self, url, *, params=None, partition=False, maximum=MAX_RESPONSE, deadline=None):
        safe_url(url, partition=partition)
        for _ in range(4):
            try:
                require(deadline is None or time.monotonic() < deadline, "source_unavailable")
                response = self.session.get(url, params=params, timeout=(5, 45),
                                            allow_redirects=False, stream=True)
                if 300 <= response.status_code < 400:
                    location = response.headers.get("Location", "")
                    url = urljoin(url, location)
                    safe_url(url, partition=partition)
                    # Do not forward the key to redirects or a different endpoint.
                    require(not params or "api_key" not in params, "unsafe_url")
                    continue
                if not 200 <= response.status_code < 300:
                    raise RegulatoryError("source_http_error")
                declared = response.headers.get("Content-Length")
                if declared is not None:
                    require(declared.isdecimal() and int(declared) <= maximum, "response_too_large")
                content = bytearray()
                for chunk in response.iter_content(chunk_size=65536):
                    require(deadline is None or time.monotonic() < deadline, "source_unavailable")
                    content.extend(chunk)
                    require(len(content) <= maximum, "response_too_large")
                return bytes(content)
            except (requests.RequestException, OSError):
                raise RegulatoryError("source_unavailable") from None
            finally:
                if "response" in locals():
                    response.close()
        raise RegulatoryError("unsafe_url")

    def query(self, expression: str, *, limit: int = 100, skip: int = 0, retrieved_at: str | None = None):
        safe_query_scope(expression)
        require(type(limit) is int and 1 <= limit <= 1000 and type(skip) is int and
                skip == 0, "invalid_scope")
        require(bool(self.api_key), "invalid_scope")
        deadline = time.monotonic() + 180
        payload = self._get(API_URL, params={"search": expression, "limit": limit,
                                             "api_key": self.api_key}, maximum=25_000_000, deadline=deadline)
        snapshot = normalize_response(parse_json(payload), method="query", scope=expression,
                                      retrieved_at=retrieved_at or _now(), raw_bytes=payload)
        require(snapshot["retrieval"]["observed_count"] == limit or
                snapshot["retrieval"]["observed_count"] == snapshot["retrieval"]["source_total"],
                "incomplete_ingestion")
        return snapshot

    def bulk(self, *, retrieved_at: str | None = None):
        deadline = time.monotonic() + 1800
        manifest_bytes = self._get(MANIFEST_URL, maximum=5_000_000, deadline=deadline)
        manifest = object_value(parse_json(manifest_bytes))
        dataset = object_value(object_value(object_value(manifest.get("results")).get("drug")).get("drugsfda"))
        stamp = dataset_date(dataset.get("export_date"))
        partitions = array_value(dataset.get("partitions"))
        require(bool(partitions) and len(partitions) <= 100, "incomplete_ingestion")
        require(all(type(p) is dict for p in partitions), "malformed_source")
        total = dataset.get("total_records")
        require(type(total) is int and total >= 0, "malformed_source")
        require(all(type(p.get("records")) is int and p["records"] >= 0 for p in partitions), "malformed_source")
        require(sum(p["records"] for p in partitions) == total,
                "incomplete_ingestion")
        seen = set()
        records = []
        locators = []
        digests = []
        meta = None
        for entry in partitions:
            entry = object_value(entry)
            url = safe_url(entry.get("file"), partition=True)
            require(url not in seen, "incomplete_ingestion")
            seen.add(url)
            count = entry.get("records")
            require(type(count) is int and count >= 0, "malformed_source")
            zipped = self._get(url, partition=True, maximum=40_000_000, deadline=deadline)
            raw, _ = extract_zip(zipped)
            body = object_value(parse_json(raw))
            rows = array_value(body.get("results"))
            require(len(rows) == count, "incomplete_ingestion")
            part_meta = object_value(body.get("meta"))
            numbers = object_value(part_meta.get("results"))
            require(all(type(numbers.get(k)) is int for k in ("total", "limit", "skip")) and
                    numbers["total"] == count and numbers["limit"] == count and
                    numbers["skip"] == 0, "incomplete_ingestion")
            if meta is None:
                meta = part_meta
            else:
                require(all(part_meta.get(k) == meta.get(k) for k in
                            ("disclaimer", "terms", "license", "last_updated")),
                        "incomplete_ingestion")
            records.extend(rows)
            locators.extend(f"{url}#results[{index}]" for index in range(len(rows)))
            digests.append({"url": url, "sha256": hashlib.sha256(zipped).hexdigest()})
        require(len(records) == total, "incomplete_ingestion")
        # Canonicalize only the synthetic in-memory joined envelope, never mislabel it raw.
        joined = {"meta": {**meta, "results": {"total": total, "limit": total, "skip": 0}},
                  "results": records}
        return normalize_response(joined, method="bulk", scope=None,
                                  retrieved_at=retrieved_at or _now(), raw_bytes=manifest_bytes,
                                  dataset_timestamp=stamp, source_total=total,
                                  partition_digests=digests, record_locators=locators)


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")