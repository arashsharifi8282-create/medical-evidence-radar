# Phase B7 M0 — FDA source-contract verification (2026-09-26)

Scope: Drugs@FDA application metadata only. Reviewed official documentation:
https://open.fda.gov/apis/drug/drugsfda/understanding-the-api-results/ ,
https://open.fda.gov/apis/downloads/ ,
https://open.fda.gov/apis/authentication/ and https://open.fda.gov/terms/ .
Bounded direct GETs (requests, redirects disabled, no key) to
https://api.fda.gov/drug/drugsfda.json (search application_number:NDA020123,
limit 1), https://api.fda.gov/download.json and the one currently listed
Drugs@FDA ZIP. No document links fetched. This is source-contract inspection,
not keyed production verification.

Observed API `meta`: disclaimer, terms, license, last_updated, results;
`results` is an array. Applications contain application_number, sponsor_name,
optional products/submissions/openfda; document links are nested in submissions.
Manifest `results.drug.drugsfda`: export_date `2026-09-26`, total_records
29350, one partition (NOT a fixed count), with file, records, size_mb. ZIP was
9,351,826 bytes; its one JSON member was 124,787,344 bytes with a meta/results
envelope of 29350 records. Bulk meta.last_updated was `2026-09-26` and
meta.results.total/limit were 29350. Dataset dates used `YYYY-MM-DD`; sampled
submission/document dates used calendar `YYYYMMDD`. `application_docs.title`
was absent on 79,962 of 80,941 document links. One submission lacked optional
submission_status. The API sample contained HTTP document links: never fetch.
No application-wide status or per-record version observed.

Across all 29350 downloaded records: zero missing/empty application_number,
zero duplicate application_number; zero missing/duplicate product_number and
zero missing/duplicate submission (type, number) per application. This supports
the proposed strict identity policy for the *current* export only, not future
guarantees. If future source records violate it, fail closed and seek approval
for a versioned policy change. `application_docs.id` remains opaque and is not
promoted to independent identity. Unrecognized codes stay raw; Discontinued
does not mean application withdrawal.

Official terms describe generally CC0 metadata with exceptions for third-party
works, optional attribution and no warranty. Official authentication guidance
calls for a free API key while documenting keyless quotas. The historical M0
inspection found `OPENFDA_API_KEY` absent locally and observed HTTP 200 only on
unkeyed requests. **D3:** current identity/manifest/schema gate supports strict
version 1.0, subject to future fail-closed drift. **D6:** see the final
acceptance note below; no credential was requested in chat or persisted.

## Remediation review (2026-09-26)

**Verified source shape (bounded, historical):** the inspected 29,350-record
export and one unkeyed query had the shapes and identity properties above.
These observations do not establish a guarantee for subsequent exports. No
additional live source requests were made during remediation.

**Accepted normalization policy:** retain exact application/product/submission
identifiers or fail closed; keep application status unknown; carry source dates
only at their documented scope; store exact response/manifest and per-partition
SHA-256 plus canonicalized record digests. Complete raw bytes are not stored;
the snapshot's `audit.warnings` says so. `source_fields` retains mapped nested
field values/paths, not unknown source field values or full raw records.

**Unverified semantics:** future export identity and optional-field behavior,
meaning of unknown source codes and `application_docs.id`, per-record version
(none observed), and rights of linked documents (never downloaded). M0 did
not authenticate a key or validate every future partition/JSON size limit.
If new source facts require different identities, mappings, required keys or
storage fields, obtain D3/product approval for a versioned schema/policy change
before publishing rather than silently changing `b7/1.0`.

## Offline hardening calibration (2026-09-26)

The inspected export provides bounded, historical size evidence only: the ZIP
was 9,351,826 bytes and the single JSON member was 124,787,344 bytes. The B7
limits are therefore 40,000,000 compressed ZIP bytes (about 4.2 times that
observed ZIP) and 200,000,000 member/response JSON bytes (about 1.6 times that
observed member), one member per partition (the inspected source had one), a
100-level JSON depth limit, and a 10,000,000-node parser ceiling. Query calls
have a 180-second end-to-end deadline; a complete bulk run has a 1,800-second
end-to-end deadline; each request retains the existing `(5, 45)` connect/read
timeout. These are conservative operational bounds, not assertions about all
future export sizes. A source exceeding them fails closed and needs a
source-contract/product review before a limit or schema policy changes.

Offline adversarial verification includes duplicate JSON keys, malformed and
truncated ZIPs, traversal, symlink, multi-member and compression-bomb archives,
unsafe redirects, credential-bearing URLs (including client-secret/signature
aliases), malformed counts, depth/node limits, interrupted streams and marker-
less publication recovery. The independent synthetic expected-code catalogue is
checksummed in `tests/fixtures/b7_regulatory/adversarial_expectations.json`.

## R12 provenance and approved raw-retention disposition (2026-09-26)

**PASS against the approved `b7/1.0` digest-plus-disclosure policy.** Each
supported normalized application, product, active-ingredient, submission, and
application-document field retains a controlled `source_fields` entry with its
observed value state (`absent`, `null`, or `present`), retained raw value and
precise nested source path. Application-level provenance retains the source
authority/system/jurisdiction/document type, immutable application identity,
source record locator, retrieval method and versioned normalization, identity,
version and status policies. The persisted validator rejects changed mapped
values, paths, identities and semantic digests.

`raw_source_reference` retains the per-record canonical SHA-256 and, when
available, the response SHA-256. Query observations retain the response digest;
complete bulk observations retain the manifest response digest plus an exact
ZIP SHA-256 and URL for every accepted partition. The snapshot-level canonical
semantic digest detects retained semantic changes. Controlled synthetic source
fixtures exercise these mappings and the validator's corruption rejection.

Raw response bytes, complete raw records, and unknown source fields are not
retained. `audit.warnings` explicitly says that loss is intentional; those
bytes cannot be reconstructed from a B7 snapshot, and a digest alone cannot
authenticate a retained mapping without independently retained source bytes.
This is the approved policy, not a claim of reconstructability. No stronger
retention guarantee is claimed; a request to require raw reconstruction would
need a separately approved, versioned schema and retention-policy amendment.

## R24 query-scope and privacy contract (2026-09-26)

Before a query request, B7 accepts a non-empty UTF-8 openFDA search expression
of at most 2,048 characters with no control characters. It intentionally allows
ordinary biomedical field expressions and terminology; it does not whitelist
drug, condition, sponsor or other source vocabulary. It rejects clear
credential-bearing parameter forms (`api_key`, access token, authorization,
client secret, password, signature and aliases), explicit patient-identifier
field names, and recognizable email, US SSN and phone-number literals. The
same deterministic policy is applied again when validating persisted query
scope, so manually forged unsafe audit metadata cannot be serialized.

The adapter sends the API key only as the transport `api_key` parameter to the
pinned HTTPS API endpoint. Redirects never forward that parameter; endpoint,
partition and source-link validation reject credential-bearing URLs. Stable
error codes contain no request, response or credential text, and JSON,
Markdown and HTML derive only from validated snapshot data. Query scope remains
visible in audit metadata only after passing this screen.

This deterministic filter cannot detect every possible sensitive phrase or
identifier embedded in arbitrary free text and is not a claim of comprehensive
PHI/PII detection. Operators must not submit patient-specific or otherwise
sensitive free-text queries. This policy changes validation behavior only and
does not alter the approved `b7/1.0` persisted schema.

**D6 setup (local only):** a supplied key must be
entered only through a local secure Windows input prompt or Environment
Variables UI; do not put it in command history, configuration files or chat.
Persist it as the Windows **User** `OPENFDA_API_KEY` variable, start a fresh
PowerShell process so it inherits the setting, then use the following bounded
one-result query through the real B7 adapter. Do not run core CI with network.

```powershell
.\.venv\Scripts\python.exe -m app.sources.regulatory.cli --source fda-drugsfda --query 'application_number:NDA020123' --limit 1 --save --data-dir data\regulatory\d6-verification --report-dir reports\regulatory\d6-verification --name fda_nda020123_keyed
Before completing R22, record the date, exact bounded scope, HTTP/auth
success or sanitized error code, observed response shape, normalized count,
source attribution, and a credential-redaction check on any separately saved
artifacts. Do not paste/store the key or credential-bearing request URL. The
unkeyed M0 inspection is not a substitute for D6.

## Historical D6 narrative (2026-09-26; superseded as an audit record)

The following narrative preserves the original claimed D6 observation and its
facts, but it did not preserve a durable child-process execution record that an
independent reviewer could reconstruct. It is therefore historical context, not
the basis for independent acceptance.

**Stable execution and credential handling:** one managed local Windows
PowerShell child process was launched from a fresh environment and supervised
with a 240-second outer timeout. The child checked only that
`OPENFDA_API_KEY` was nonempty; the value was not displayed, logged, persisted,
passed as a command argument, or included in this document. The temporary
stdout/stderr capture was empty and was removed after inspection. A prior
launcher setup failure occurred before any B7 CLI invocation or FDA request;
it is not counted as a source, authentication, network, or adapter result.

**Single bounded production invocation:** the real B7 CLI used the documented
FDA Drugs@FDA query `application_number:NDA020123`, `--limit 1`, and `--save`
with dedicated `data/regulatory/d6-verification` and
`reports/regulatory/d6-verification` directories and the name
`fda_nda020123_keyed`. It did not request PDFs or linked documents. The managed
child completed the CLI success path with **exit code 0**. The CLI does not
surface a raw HTTP status in its safe output, so this is recorded as a
successful keyed adapter/CLI result rather than an invented HTTP status.

**Sanitized FDA source verification:** the accepted response normalized as one
`b7/1.0` bounded-query record: `observed_count=1`, `source_total=1`, and
`audit.record_count=1`. Its identity is `NDA020123`; its provenance is FDA /
openFDA / US, `drug_application`, query retrieval, and the pinned HTTPS API
endpoint. The persisted retrieval metadata records source dataset timestamp
`2026-09-24` with kind `meta.last_updated`, and raw response SHA-256
`684504b5758ec77c55dc6f52d47acd887fff65f0f12357d2b2423ec00f827eef`.
Successful normalization and the loaded snapshot's record-count agreement are
the response-envelope validation evidence; no raw response body or
credential-bearing request URL was retained.

**Saved-artifact completion and redaction:** the generation is complete only
with `fda_nda020123_keyed.complete`; JSON, Markdown, and HTML are present and
match its completion-marker checksums. Loading the published snapshot succeeded,
and the Markdown and HTML bytes exactly regenerated from the validated JSON.
The four saved artifacts were scanned in memory against the exact inherited
credential without revealing it: no match was found. They also contained none
of the credential-bearing URL markers screened by the verification
(`api_key`, authorization, bearer, client-secret, access-token, password,
signature, or `sig` parameter forms).

**Historical disposition:** this was previously described as complete. The
claim is superseded for auditability purposes by the controlled attestation
record below; it does not itself establish independent-review PASS.

## Controlled D6 execution attestation (2026-09-26)

The remediation run used `scripts/run_b7_d6_attestation.py` with a dedicated,
ignored local `data/regulatory/d6-remediation-20260927` and
`reports/regulatory/d6-remediation-20260927` directory. It launched one real
B7 CLI child with the approved FDA Drugs@FDA query
`application_number:NDA020123`, `--limit 1`, and `--save`; no PDF or linked
document retrieval was requested. `OPENFDA_API_KEY` was recorded only as a
present/absent boolean. The key, its hash, headers, credential-bearing URLs,
raw stdout/stderr, raw FDA bytes, and patient-specific data were not retained.

The durable local `b7-d6-attestation/1.0` records execution start
`2026-09-26T21:38:27Z`, finish `2026-09-26T21:38:29Z`, and the actual child exit
code `0` with safe classification `success`. It records one `b7/1.0`
FDA/openFDA/US `drug_application` observation (`NDA020123`), query retrieval,
source dataset timestamp `2026-09-24` (`meta.last_updated`), normalized count
one, and semantic snapshot SHA-256
`8e58bc75a03d916c5399f5c17b3e5615eb33adb1b5c9e1671e3f212b48552fae`.

The generated JSON, Markdown, and HTML SHA-256 values were respectively
`d8c171d081d52c9a9f810e18a6c383bef5b348a3544044d681e5ecec21bca1b9`,
`5973dace55a273cf5924d9ed9864b66b8b131595e08fa56e78765bab271536d9`, and
`831e8b6cc34a2ce07f6633ec1eb8667380493292c9098638301117ddddef53bd`.
The completion marker verified those same values; the existing published-
snapshot loader independently reloaded the JSON and regenerated identical
Markdown/HTML. An in-memory scan confirmed the exact credential and screened
credential URL markers were absent. No raw HTTP status is claimed because the
CLI does not expose one safely.

This attestation is an auditable local observation, **not cryptographic proof
of historical FDA server behavior**. It supports implementation evidence for
R03, R13, and R22 alongside the D3 source-contract review. Future source drift,
continuing key access, and independent-review acceptance remain open. B7 is
uncommitted and unreleased.