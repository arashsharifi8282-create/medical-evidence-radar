"""Fail-closed source-shape, date, URL, JSON and ZIP checks for Drugs@FDA."""
from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import date, datetime
from urllib.parse import urlsplit

API_URL = "https://api.fda.gov/drug/drugsfda.json"
MANIFEST_URL = "https://api.fda.gov/download.json"
MAX_RESPONSE = 200_000_000
MAX_ZIP = 40_000_000
MAX_JSON = 200_000_000
# M0 observed exactly one JSON member in each Drugs@FDA partition archive.
MAX_MEMBERS = 1
MAX_JSON_DEPTH = 100
# The observed M0 bulk export contains 29,350 records; a 100k-node cap would
# reject legitimate ingestion. Bound the tree well above that inspected size.
MAX_JSON_NODES = 10_000_000

# Query scopes are retained in B7 audit metadata.  Allow ordinary openFDA search
# expressions (including biomedical terms), but reject clear secret transport,
# explicit patient-identifier fields, and common literal identifiers before any
# request or persistence action.  This deterministic screen cannot identify all
# sensitive free text; callers remain responsible for safe query selection.
_QUERY_CREDENTIAL = re.compile(
    r"(?:api[_-]?key|access[_-]?token|authorization|token|client[_-]?secret|"
    r"password|signature|sig)\s*=", re.I)
_QUERY_PATIENT_FIELD = re.compile(
    r"\b(?:patient(?:[_-]?name|[_-]?id)?|name|email|e[_-]?mail|ssn|"
    r"social[_-]?security|dob|date[_-]?of[_-]?birth|phone|telephone)\s*:", re.I)
_QUERY_EMAIL = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
_QUERY_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_QUERY_PHONE = re.compile(r"(?<!\w)(?:\+?1[ .-]?)?(?:\(?\d{3}\)?[ .-]?)\d{3}[ .-]\d{4}(?!\w)")


class RegulatoryError(Exception):
    """Stable code and non-source-derived, credential-free message."""

    def __init__(self, code: str, message: str = "Regulatory source validation failed"):
        super().__init__(message)
        self.code = code


def require(condition: bool, code: str) -> None:
    if not condition:
        raise RegulatoryError(code)


def safe_query_scope(expression: str) -> str:
    """Validate a bounded, non-credential, non-patient-specific openFDA scope.

    The function intentionally does not whitelist source field names or medical
    vocabulary: legitimate biomedical search syntax remains usable.  It only
    rejects unambiguous high-risk forms and cannot prove arbitrary free text is
    non-sensitive.
    """
    require(type(expression) is str and bool(expression.strip()) and len(expression) <= 2048 and
            not any(ord(character) < 32 or ord(character) == 127 for character in expression) and
            not _QUERY_CREDENTIAL.search(expression) and not _QUERY_PATIENT_FIELD.search(expression) and
            not _QUERY_EMAIL.search(expression) and not _QUERY_SSN.search(expression) and
            not _QUERY_PHONE.search(expression), "invalid_scope")
    return expression


def safe_url(url: str, *, partition: bool = False) -> str:
    require(isinstance(url, str), "unsafe_url")
    try:
        parts = urlsplit(url)
        hostname, port = parts.hostname, parts.port
    except ValueError:
        raise RegulatoryError("unsafe_url") from None
    if partition:
        allowed = (hostname == "download.open.fda.gov" and
                   re.fullmatch(r"/drug/drugsfda/[A-Za-z0-9_.-]+\.json\.zip", parts.path))
    else:
        allowed = url in (API_URL, MANIFEST_URL)
    require(bool(allowed) and parts.scheme == "https" and not parts.username and
            not parts.password and not parts.query and not parts.fragment and
            port is None, "unsafe_url")
    return url


def source_link(value):
    """Keep source links as text only, and reject credential-bearing URL parameters."""
    if value is None:
        return None
    require(type(value) is str, "malformed_source")
    try:
        parts = urlsplit(value)
    except ValueError:
        raise RegulatoryError("malformed_source") from None
    require(parts.scheme in ("http", "https") and bool(parts.hostname) and
            not parts.username and not parts.password and
            not re.search(r"(?:^|[&;])(?:api[_-]?key|access[_-]?token|authorization|token|client[_-]?secret|password|signature|sig)=", parts.query, re.I),
            "malformed_source")
    return value


def object_value(value):
    require(type(value) is dict, "malformed_source")
    return value


def array_value(value):
    require(type(value) is list, "malformed_source")
    return value


def source_text(value, *, required=False, identifier=False):
    if value is None and not required:
        return None
    require(type(value) is str, "missing_identifier" if identifier else "malformed_source")
    if required:
        require(bool(value.strip()), "missing_identifier" if identifier else "malformed_source")
    return value


def nested_id(value):
    require(type(value) is str and bool(value.strip()), "missing_nested_identifier")
    return value


def optional_date(obj, name):
    """Only missing/null optional dates are allowed to normalize to null."""
    if name not in obj or obj[name] is None:
        return None
    return source_date(obj[name])


def source_date(value):
    if value is None:
        return None
    require(type(value) is str and bool(re.fullmatch(r"\d{8}", value)), "invalid_source_date")
    try:
        return date(int(value[:4]), int(value[4:6]), int(value[6:])).isoformat()
    except ValueError:
        raise RegulatoryError("invalid_source_date") from None


def dataset_date(value):
    if value is None:
        return None
    require(type(value) is str and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)), "invalid_source_date")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise RegulatoryError("invalid_source_date") from None
    return value


def utc_date(value):
    require(type(value) is str and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value)), "invalid_source_date")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise RegulatoryError("invalid_source_date") from None
    return value


def parse_json(content: bytes):
    require(type(content) is bytes and len(content) <= MAX_JSON, "response_too_large")
    try:
        def unique(pairs):
            result = {}
            for key, val in pairs:
                if key in result:
                    raise RegulatoryError("invalid_json")
                result[key] = val
            return result
        value = json.loads(content, object_pairs_hook=unique,
                           parse_constant=lambda _: (_ for _ in ()).throw(RegulatoryError("invalid_json")))
        pending = [(value, 1)]
        visited = 0
        while pending:
            node, depth = pending.pop()
            visited += 1
            require(visited <= MAX_JSON_NODES and depth <= MAX_JSON_DEPTH, "response_too_large")
            if type(node) is dict:
                pending.extend((child, depth + 1) for child in node.values())
            elif type(node) is list:
                pending.extend((child, depth + 1) for child in node)
        return value
    except (UnicodeError, ValueError, RecursionError):
        raise RegulatoryError("invalid_json") from None


def extract_zip(content: bytes) -> tuple[bytes, str]:
    require(type(content) is bytes and len(content) <= MAX_ZIP, "response_too_large")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members = archive.infolist()
            require(len(members) == 1 and len(members) <= MAX_MEMBERS, "invalid_zip")
            member = members[0]
            require(bool(re.fullmatch(r"[A-Za-z0-9_.-]+\.json", member.filename)) and
                    member.file_size <= MAX_JSON and member.compress_size > 0 and
                    member.file_size <= member.compress_size * 200 and
                    member.compress_type in (zipfile.ZIP_DEFLATED, zipfile.ZIP_STORED) and
                    not member.flag_bits & 1 and
                    ((member.external_attr >> 16) & 0o170000) != 0o120000,
                    "invalid_zip")
            with archive.open(member) as stream:
                payload = stream.read(MAX_JSON + 1)
            require(len(payload) == member.file_size and len(payload) <= MAX_JSON, "invalid_zip")
            return payload, member.filename
    except (zipfile.BadZipFile, OSError, RuntimeError, EOFError):
        raise RegulatoryError("invalid_zip") from None