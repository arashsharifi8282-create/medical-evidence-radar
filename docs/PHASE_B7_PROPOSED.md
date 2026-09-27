# Phase B7 — Official regulatory metadata (proposed specification)

## Active implementation and review status (2026-09-26)

- **Approved product scope:** D1 FDA Drugs@FDA application metadata only; D2
  metadata-only/no-PDF rights boundary; D4 no B6 extension or cross-format
  comparison; D5 roadmap correction; D3 `b7/1.0` policy conditional on
  fail-closed future source drift. D7 remains deferred.
- **Completed implementation:** the additive FDA-only B7 model, validation,
  adapter, normalizer, persistence, CLI, synthetic fixtures, and offline tests
  exist in the uncommitted working tree. B5/B6 production code is unchanged.
- **Recorded D6 keyed verification:** the controlled September 26, 2026
  `application_number:NDA020123`, limit-1, saved CLI run has a durable local
  `b7-d6-attestation/1.0` with actual child exit `0`, one normalized record,
  artifact digests, completion-marker/renderer checks, and credential-redaction
  outcomes. See `PHASE_B7_D6_ATTESTATION_CONTRACT.md` and the M0 record.
- **Independent acceptance:** the first independent acceptance review
  was **REJECTED / BLOCKED** for documentation and D6-process-auditability
  remediation. Its prior 374/374 canonical result is implementation evidence,
  not acceptance. The second independent acceptance review concluded
  **ACCEPTED — READY FOR RELEASE PREPARATION** (F1–F4 resolved, R01–R25
  PASS, D6 attestation accepted; independently executed 109 focused B7 and
  378 canonical tests, 5/5 fixture checksums). This release commit records
  that acceptance; GitHub publication is verified separately after push.
**Release state:** B7 is implemented and accepted for release preparation
under the second independent review. This release commit is the publication
vehicle; `v0.7.0` exists only after the annotated tag is created and its
remote publication is verified.

**Historical proposal below (superseded where it says B7 is unimplemented, all
decisions are pending, or D6 was never executed):** the retained text records
the original product rationale and acceptance contract. “MUST” in that
historical proposal describes its intended contract; it is not a claim that a
release has been accepted. Research basis: `docs/PHASE_B7_RESEARCH_PACKAGE.md`
§§0–8, retrieved 2026-09-26. Do not use this tool for medical care or interpret
record presence as an individual approval or treatment recommendation.

## 1. Purpose and problem statement

The current system retrieves PubMed articles and compares two explicitly supplied `b5` evidence snapshots by PMID. Official regulatory application metadata is a different evidence genus with different authority, identity and update semantics. B7 proposes an independent, reproducible research-support record of what an official source actually supplied. It must not treat a drug mention as regulatory approval, therapeutic efficacy or applicability.

## 2. Product objective

Enable bounded, source-linked, offline-auditable FDA application metadata ingestion and presentation without altering PubMed ranking, clinical extraction, report policy, B5 snapshots or B6 comparisons. A saved record represents *observed openFDA Drugs@FDA metadata*, not the full authoritative application dossier or a regulatory determination. JSON is the audit authority; a short Markdown and escaped standalone HTML view may project only JSON facts.

## 3. Proposed MVP and alternatives

| Choice | Authority / category / jurisdiction | Coverage and data availability | Version feasibility; dependencies | Risk, limitation, acceptance implications |
|---|---|---|---|---|
| **A — recommended, pending approval** | FDA via openFDA `drug/drugsfda`; application records (products, submission history, document-link metadata); US | Documented JSON query API and bulk manifest/ZIP. Metadata only; no linked document bytes. Source says *most* products since 1939, documents largely since 1998; not an exhaustive registry guarantee. | Dataset-level date plus explicitly retained local snapshots and SHA-256, **not** a per-record change feed. Requires source validation, bounded retrieval, key decision, identity/serialization policies. | Clear authority and permissive documented metadata terms; no authoritative per-application version or withdrawal feed. Acceptance must include complete-run/scope audits, not claim comprehensive coverage from a query. |
| B | EMA medicines JSON only; centrally authorised medicine/product records; EU central scope (not every member-state authorisation) | Official JSON data for automated use, medicine status and lifecycle dates; attribution on each reused copy. | File-level timestamp/Last-Modified, locally retained versions; separate EMA model and status policy; investigate schema stability and rate limits. | Different identity and jurisdiction/status vocabulary; not substitutable for FDA applications. Acceptance requires attribution, EMA-specific fixtures, EU-scope warnings and stability review. Defer. |
| C | FDA applications **plus** EMA centrally authorised medicines; US and EU-central | Both official machine-readable sources, but *two different record categories*, not one harmonized status. | Separate adapters, validation, legal notices and source-level versions; no safe shared status comparison. | Doubles policy and validation surface; only acceptable if independently approved with both source gates. Rejected for MVP. |

FDA is first because the checkpoint verifies structured application/submission/product fields, bulk export, dataset timestamps and openFDA metadata reuse terms. EMA is a credible later candidate but cannot be quietly substituted; WHO IRIS metadata/status and rights are insufficiently established for this contract; NICE syndication requires organisational licensing and certification. No future source is pre-approved by this recommendation. [Research §§3–5](PHASE_B7_RESEARCH_PACKAGE.md).

## 4. Supported authority

Only `source_authority="FDA"`, `source_system="openFDA"`, dataset `drug/drugsfda`. Explicit source allowlist; unsupported source fails closed. openFDA harmonization fields (`rxcui`, etc.) may be retained as raw data, not treated as resolved concept or evidence relationships.

## 5. Supported document categories

Only `document_type="drug_application"` at application-record granularity. Nested submissions, products and `application_docs` are components, **not** separate approved documents or PDF contents. No FAERS, labeling, NDC, shortages, Orange Book, enforcement, guidances or Federal Register.

## 6. Jurisdiction

`jurisdiction="US"` records this source's scope; it is not an inference about where a particular product may be sold or clinically used. Do not transfer findings across authorities, countries, indications or products.

## 7. Source access and licensing

Official endpoint `https://api.fda.gov/drug/drugsfda.json`, bulk manifest `https://api.fda.gov/download.json`, manifest-listed ZIP at `https://download.open.fda.gov/` only. The checkpoint verifies a current single Drugs@FDA partition, *not* a guaranteed perpetual partition count; discover all manifest partitions and validate completeness. API query calls require an explicit user-supplied search expression; bounded `limit`/`skip` (documented max 1000/25000); no unverified `search_after` contract. Full enumeration uses bulk, not paginated search. Authentication page says key required but publishes keyless quotas: 240/min and 1,000/day/IP, keyed 240/min and 120,000/day/key; key free. **Operational policy:** use a key for API search after decision D6, avoid relying on keyless service for release validation; bulk accessibility/auth must be checked in live verification, not assumed. No promise of availability or unchanged quotas. Preserve `meta.disclaimer` and applicable `meta.terms`/`license` if supplied.

FDA's openFDA terms say openFDA content is generally CC0/public domain *unless otherwise noted*, attribution requested, not required. Store metadata with source credit nonetheless. Third-party copyrighted materials can be excluded; a linked PDF is not licensed merely because its URL appears in an official record. **Never fetch or redistribute linked PDF/full text in B7**. Recheck relevant terms and any field-specific warning before external distribution; this is not legal advice. Cache only bounded validated raw metadata/manifest and ZIP as local audit outputs; do not publish raw third-party content. No access-limit circumvention. Targeted official-documentation recheck on **2026-09-26**: [authentication](https://open.fda.gov/apis/authentication/), [terms](https://open.fda.gov/terms/), [bulk download format](https://open.fda.gov/apis/downloads/), [Drugs@FDA results structure](https://open.fda.gov/apis/drug/drugsfda/understanding-the-api-results/). Bulk files are described as zipped JSON in the same general format as query results; this does **not** establish the exact live ZIP member schema. [Manifest](https://api.fda.gov/download.json), partition observations, field dictionary/code vocabulary, signup backend and PDF rights remain checkpoint-sourced or unverified as labelled in research §4.1; no live download or key validation was performed here.

## 8. Proposed architecture and implementation boundary

Data flow: explicit CLI selection (query **or** manifest bulk) → injectable `requests.Session` adapter → transport and envelope/bulk-integrity validator → pure FDA normalizer → frozen regulatory models → independent regulatory persistence → audit JSON and JSON-derived MD/HTML. No import from PubMed `Article`/ranking, and no policy activation in `config/report_policy.json`.

| Component (proposed path) | Responsibility; input → output | Why / dependency / offline test |
|---|---|---|
| `app/sources/regulatory/fda_openfda.py` | Explicit query or manifest, HTTPS allowlist, bounded response/ZIP, timeouts, injected session → raw response bytes + transport metadata; no interpretation | Mirrors PubMed fake-transport convention; test URLs, redirects, pagination boundaries, errors, interruptions. |
| `app/sources/regulatory/validation.py` | JSON shape, envelope, manifest partitions/counts, date and ID types, ZIP constraints → validated collection and structured diagnostics | Standard library `json`, `zipfile`, `hashlib`; test corrupt/truncated/oversized/schema-drift data. |
| `app/models/regulatory_document.py` | Frozen typed application, submission, product, doc-link and provenance values → immutable normalized record | Independent identity from `Article`; test null/multiple nested entities. |
| `app/services/regulatory_normalizer.py` | Validated FDA dict + source context → canonical `b7/1.0` application dicts or `RegulatoryError`; no network | Rule/version pinned; table-driven fixtures, reorder/digest tests. |
| `app/services/regulatory_persistence.py` | Canonical snapshot → deterministic JSON + source-faithful MD/HTML and safe filenames in `data/regulatory/`, `reports/regulatory/` | Keep B5 serializer unchanged; test read-back, escaping, digest, incomplete-write cleanup. |
| `app/sources/regulatory/cli.py` | `--source fda-drugsfda` and exactly one of `--query <expression>` / `--manifest`, `--save` explicit; optional output directories → paths or exit 2 | No default query, auto-scan, scheduler or auto-baseline; test offline invocation and no-success-artifact errors. |

Source adapter may offer an offline `normalize_saved_response` seam for controlled fixtures; never allow a local file path or query to override the remote host. No new runtime dependency is assumed (existing `requests`, stdlib). Future generic adapter interfaces are justified only when a second authority is separately approved.

## 9. Canonical `b7/1.0` snapshot and record schema

Strict JSON object; known keys and types only in normalized output. Required keys cannot be absent. Nullable means present with JSON `null`; absent optional *source* fields stay absent in `raw_field_state` and become `null` in the designated normalized nullable slot. Source strings are never silently substituted. Numbers/booleans are never cast to strings. This is a **proposed B7 storage contract**, not an openFDA response schema.

| Level / field | Type, rule and source |
|---|---|
| Snapshot `schema_version`, `source_authority`, `source_system`, `document_type`, `jurisdiction` | Required strings `b7/1.0`, `FDA`, `openFDA`, `drug_application`, `US`. |
| Snapshot `normalization_version`, `identity_policy_version`, `version_policy_version`, `status_policy_version` | Required string `1.0` each; unsupported versions fail closed. |
| Snapshot `retrieval` | Required object: `method` enum `query`/`bulk`, `source_url` (validated HTTPS endpoint **without credentials/query secrets**), `query` nullable string (only query mode; never an API-key-bearing expression), `retrieved_at` required UTC ISO-8601 with `Z`; `dataset_timestamp` nullable source string plus `dataset_timestamp_kind` enum `meta.last_updated`/`export_date`/`unavailable`; `completeness` enum `complete_bulk`/`bounded_query` (no complete search claim); `source_total` nullable integer; `observed_count` integer; `partition_count` nullable integer; `partition_digests` array of `{url,sha256}` over exact downloaded ZIP bytes for bulk; `source_disclaimer`, `source_terms_url`, `source_license_url` nullable strings; `raw_response_sha256` SHA-256 over exact API response bytes for query or exact manifest bytes for bulk. Timestamp claim is *source-stated*, not record revision. |
| Snapshot `records`, `audit` | Array of canonical application records and audit object `{warnings:[], source_field_coverage:{}, record_count:int, snapshot_semantic_sha256:string}`. MVP: missing identifier aborts; do not silently drop or create unmatched pseudo-records. |
| Record `source_document_id`, `canonical_identity` | Required nonempty application number string from `application_number`, exact source value (no prefix conversion, no synthetic IDs); identity structured object `{source_authority,document_type,source_document_id}`. Duplicate in one retrieval fails closed. |
| Record `title`, `sponsor_name`, `publication_date` | `title=null`, since no verified application title field; no manufactured title from product name. `sponsor_name` nullable string from same field. `publication_date=null`: submission status date is **not** publication date. |
| Record `canonical_url` | Required constant `https://api.fda.gov/drug/drugsfda.json` (dataset endpoint, **not a per-record permalink**); pair with application ID and separate retrieval query to locate observed data. |
| Record `raw_field_state` | Required object for every recognized top-level source field, mapping field names to `absent`/`null`/`present` without conflation. Nested `source_fields` carry the raw value and path for every present recognized nested source field. |
| Record `document_status`, `needs_review`, `review_reasons` | Required `document_status="unknown"`, boolean and sorted string array. No FDA application-wide status mapping established; preserve product marketing and submission status *only at their respective scopes*. Unknown status does not mean unapproved. `needs_review=true` when identity-preserving data is ambiguous, unknown status vocabulary or invalid optional fields; unknown alone is not a withdrawal finding. |
| Record `submissions` | Array of `{submission_type:string,submission_number:string,submission_status:string|null,submission_status_date:string|null,application_docs:array,source_fields:object}`; type/number required together per entry or record fails `missing_nested_identifier`. Raw date format `YYYYMMDD` → ISO calendar date; invalid date fails `invalid_source_date`. Submission `application_docs` retain `{id:string|null,date:string|null,title:string|null,type:string|null,url:string|null,source_fields:object}`; metadata/links only; docs have no guaranteed stable independent identity. |
| Record `products` | Array of `{product_number:string,brand_name:string|null,marketing_status:string|null,active_ingredients:array of {name:string|null,strength:string|null},dosage_form:string|null,route:string|null,source_fields:object}`. Product number required if product supplied; otherwise fail `missing_nested_identifier`. No synthetic ingredient ID. |
| Record `provenance`, `raw_source_reference`, `content_digest` | Required provenance object `{source_authority,source_system,jurisdiction,document_type,source_document_id,source_url,source_record_locator,source_record_sha256,retrieval_method,dataset_timestamp,normalization_version,identity_policy_version,version_policy_version,status_policy_version,license_note,field_paths}`; `raw_source_reference={response_sha256,record_sha256,locator}`; `content_digest` 64-char lower hex semantic digest (§11). `locator` is `results[index]`/`partition URL + results[index]`, an observation locator **not** a stable identifier. `field_paths` maps each normalized sourced value to source JSON path (including array indices); derived values map to named rules instead. |

`source_fields` for nested entries maps field names to `{path,raw_value}` for recognized fields, including absent/null distinctions where relevant. Top-level `raw_field_state` maps recognized fields to `absent`/`null`/`present`; raw complete responses are retained only in separately checksummed local artifacts if legally/operationally permitted, never stuffed into the normalized record. Unknown source fields are **not** covered by `raw_source_reference` alone: `source_record_sha256` detects their change, while raw bytes (when retained) allow recovery. If raw bytes are not retained, record the loss explicitly in `audit.warnings`. No claim of full field-level provenance for unknown fields.

**Illustrative, invented data, NOT a real source record** (truncated to illustrate mapping; not a valid complete persisted snapshot):

```json
{"application_number":"NDA999999","sponsor_name":"Example Sponsor","submissions":[{"submission_type":"ORIG","submission_number":"1","submission_status":"AP","submission_status_date":"20260115","application_docs":[]}],"products":[{"product_number":"001","brand_name":"Example","marketing_status":"Prescription","active_ingredients":[]}]}
```

Illustrative projection: `canonical_identity={"source_authority":"FDA","document_type":"drug_application","source_document_id":"NDA999999"}`; `publication_date=null`, `document_status="unknown"`, normalized submission date `2026-01-15`; source marketing status stays on product. SHA-256 values are deliberately omitted rather than fabricated. The example does **not** assert any product actually exists or is approved.

## 10. Identity policy (`regulatory_document_identity_policy_version=1.0`)

Application key is exact tuple `(FDA, drug_application, application_number)`; require nonempty string after checking whitespace-only, preserve source spelling and do not silently trim/case-fold a valid source ID. Reject duplicate application keys, even with identical payloads; report source locators. Source pattern validation may reject impossible IDs *only* after official pattern semantics for all in-scope records are verified; default checks nonempty string, not speculative regex. Missing application ID aborts entire publish (`missing_identifier`), including records potentially marked unapproved by the source. Never reidentify by sponsor, brand, RxCUI or title.

Submission key within application `(submission_type,submission_number)`; preserve exact strings, require both nonempty; duplicate keys fail `duplicate_nested_id` unless verified source data proves non-uniqueness, in which case revise versioned policy before implementation. Product key within application is exact `product_number`; duplicate fails. `application_docs.id` is opaque and **not** trusted as unique/date-typed; identical document metadata may be retained with stable multiplicity; no independent doc identity or cross-version matching. Ingredients belong to product, no independent key. No synthetic PMID, no clinical identity matching.

## 11. Versioning and content integrity (`regulatory_version_policy_version=1.0`)

Source supplies a dataset refresh stamp, **not** a record version. Record observation key: canonical identity + `retrieval.dataset_timestamp` (nullable, with kind) + `content_digest`; two observations with identical content can still have distinct retrieval audit events. Digest uses SHA-256 UTF-8 JSON (`sort_keys=True`, separators `(',',':')`, `ensure_ascii=False`, no implicit `default=str`) over `{identity, normalization_version, status_policy_version, sponsor_name, publication_date, document_status, needs_review, review_reasons, products, submissions}` after sorting products by product key, submissions by composite key, docs by canonical metadata bytes, ingredients by canonical bytes. For nested entities, project only their normalized value fields (including raw source status strings) into the hash: **exclude** `source_fields`, index-specific paths, retrieval time, source locator/index, dataset stamp, transport metadata, rendering and raw bytes. The same normalized values in reordered arrays therefore have the same semantic hash; raw/index provenance stays separately auditable. `raw_source_reference.record_sha256` is over canonical JSON of the *complete raw source record* with stable object-key ordering and original array order; `raw_response_sha256` is over exact received bytes; unknown-field changes therefore surface as raw-only changes, not semantic changes. If record schema changes, bump the applicable version rather than changing digest behavior silently.

For a future explicitly approved B7-only comparison, `metadata_updated` means a difference in known application/product metadata; `submission_history_changed` means a change to keyed submission contents; `documents_changed` means link metadata changed; `product_marketing_status_changed` is source wording only, not withdrawal; `raw_only_changed` means raw record digest changed but semantic digest did not; `dataset_refreshed_no_record_change` means dataset stamp changed but digest did not. These are **defined vocabulary for future comparison**, not an implemented change engine. This MVP persists individual observations and digests, not pairwise change reports. No purported `document_status_changed` unless a later mapping policy has explicit application-level evidence. Do not equate `marketing_status="Discontinued"` with withdrawn application or revocation.

## 12. Normalization (`regulatory_normalization_version=1.0`)

Validate container/object/array types before normalizing; no `str(value)` coercion. Known missing/JSON-null/empty string are distinct in `raw_field_state`; optional sourced empty strings normalize to `null` with `needs_review` and a reason, keeping source value/path in `source_fields`. For required IDs empty/whitespace fails. Known submission date `YYYYMMDD` validates real Gregorian calendar → ISO `YYYY-MM-DD`; no inferred timezone, publication, effective or expiry date. A missing date becomes `null`; a malformed supplied date fails closed. Manifest `export_date` or query `meta.last_updated` is stored separately **verbatim** as a source-stated string with kind; reject non-string, whitespace-only or structurally invalid source dates after verifying their actual source format in M0, rather than guessing a format now. `retrieved_at` must parse as a real UTC timestamp; invalid strings fail closed. Do not merge source dates or call them a record update. Unknown enum values remain raw, trigger review, and are not mapped to approval/revocation. Known fields and rules only; no extraction from narrative notes, no interpretation of class codes or harmonization arrays. Treat unrecognized top-level fields as schema-drift diagnostics and cover with raw checksum, not invented normalized values.

## 13. Provenance

Every record retains authority, jurisdiction, dataset system, original application number, dataset URL, immutable observation locator and hashes; every derived field names a rule and version in `provenance.field_paths` (e.g. `document_status` → `FDA_APPLICATION_STATUS_UNMAPPED/1.0`). Every sourced field maps to its exact JSON path and original value where retained. Submission dates and marketing statuses remain attached to their originating nested entities. Reports include source credit, retrieval UTC time, source dataset timestamp/kind, source disclaimer and license note, query/scope marker, snapshot policy versions and audit hashes. Canonical endpoint URL is not a product-specific permalink. Secret-bearing request URLs/headers must be redacted before persistence.

## 14. Update contract

MVP: user explicitly fetches a query or current bulk dataset and saves a **single** complete validated observation; no scheduler, prior-snapshot auto-discovery, pairwise comparison or source-deletion inference. Bulk success requires all manifest partitions, valid ZIP and member JSON, complete parsed record counts versus declared counts when present; mismatches fail with no success artifacts. Query success means only a bounded *candidate set* with stored search expression, total/returned count and pagination scope; no exhaustive-source or absence claim. For later approved comparison require two explicit snapshots with matching authority/category, policy versions and comparable retrieval scope; query changes/partial pages are `scope_unverifiable`, never a source deletion claim. Define distinct future audit terms `no_longer_observed` (same complete bulk scope), `removed_from_observed_candidate_set` (comparable queries), `explicit_authority_withdrawal` (only explicit mapped authority field; none established in MVP), `unknown_or_unverifiable` (all other cases). No source withdrawal/revocation conclusion from disappearance or `Discontinued`. Maintain older local snapshots immutable. Dataset date equality does not prove identical record contents; digest comparison requires a separately approved comparator.

## 15. Cross-source behavior

Authority-neutral envelope: source, source-record ID, jurisdiction, category, observation time, provenance, policy/schema version and integrity digests. FDA-specific: application/submission/product keys, marketing status and source date formats. Jurisdiction-specific: US application semantics; EMA EU-central coverage is different. **Not comparable by default:** approval status, therapeutic indication, application number vs EMA product number, publication vs submission dates or rank. Future source adapters require separate versioned models/rights/status mappings and approval; side-by-side source-attributed uncertainty only, no universal classifier or automatically resolved conflicts. No WHO/NICE/EMA adapter in B7.

## 16. Error handling

Proposed `RegulatoryError(code, safe_message, source_locator)` codes: `unsupported_source`, `invalid_scope`, `source_unavailable`, `source_http_error`, `unsafe_url`, `response_too_large`, `invalid_json`, `invalid_zip`, `malformed_source`, `schema_drift`, `invalid_source_date`, `missing_identifier`, `missing_nested_identifier`, `duplicate_document_id`, `duplicate_nested_id`, `incomplete_ingestion`, `unsupported_schema_version`, `artifact_corrupt`, `artifact_write_failed`. Refuse unknown major schema/policy version, invalid timestamp, duplicate, corrupted local file and interrupted fetch. Errors omit secrets and untrusted text; optional local failure audit is separate, never a success snapshot. For network/partial-write failures, no success files; use temporary files and atomic rename after all outputs validate, with cleanup/rollback of temporary files; only publish manifest/complete marker last. Do not auto-retry into a partially committed snapshot. Stable exit 2 for fail-closed CLI errors.

## 17. Determinism

Same validated source records and same policy versions yield byte-identical *semantic* records and digests regardless of record/submission/product ordering (document/ingredient arrays sorted with multiplicity retained). Serialize sorted keys, UTF-8, `ensure_ascii=False`, indent 2 and terminal newline. Snapshot raw bytes, retrieval timestamp and locator are audit-only and can differ; record `content_digest`/snapshot `snapshot_semantic_sha256` exclude these. Snapshot digest hashes sorted `(canonical_identity,content_digest)` plus schema/policy/scope descriptors; query literal and bulk/query mode are material scope; document a deterministic sort for all audit warnings. No randomness, current clock in semantic equality, implicit defaults, fuzzy match or file-order baseline selection.

## 18. Security

Only HTTPS pinned to `api.fda.gov` and `download.open.fda.gov`, exact permitted endpoint/path families; refuse redirects unless destination is revalidated against allowlist and HTTPS at *every hop*, and bound redirect count. Never follow `application_docs` URLs. Restrict request/query size, elapsed time, bytes downloaded, ZIP member count/uncompressed bytes/compression ratio; refuse ZIP traversal, encrypted/unsupported members and symlinks. Validate JSON depth/count/shape and dates with bounded parser and response limits; confirm actual limits from representative authorized live records before production. Never execute HTML/PDF or source-provided instructions. Escape source text in Markdown/HTML; only render allowlisted safe links. API key via environment/config outside artifacts and logs, redact URL query parameters/headers/errors, avoid patient data and log only safe IDs/codes. Errors do not leak full third-party responses. Offline fake transport tests enforce these rules.

## 19. B5/B6 compatibility

`app/services/persistence.py` writes `b5`/legacy PubMed snapshots; `app/services/evidence_diff.py` accepts only valid B5-shaped snapshots, compares PMID and emits `b6/1.0`. B7 uses distinct model, normalizer, CLI, directories and `b7/1.0` snapshot. A native B7 file has no B6 `articles` list, so unchanged B6 **must reject it fail-closed as `malformed_snapshot`** before its schema-version validation, with CLI exit 2 and no B6 success artifact. This accepted gate order requires no synthetic PMIDs, no inserted `articles` field, no migration, and no changes to `Article` or `reserved_official_sources` in existing report policy. Do not feed regulatory records to B2/B3/B4 ranking or clinical report renderers. Future regulatory comparison requires independently approved identity, comparability and result schema; B6 does not provide it today. Existing B5/B6 regression suite must stay green unchanged.

## 20. Explicit exclusions

No PDF/full text or scraping linked pages; no authorization/clinical recommendation or product approval inference; no real-time change feed, scheduler, email, DB, LLM, clinical cross-matching, source ranking, multi-authority merge, universal status vocabulary, B6 extension, B8 orchestration or production changes during this documentation assignment.

## 21. Acceptance criteria, offline fixtures and execution gates

**Historical fixture specification (implemented in the current working tree):**
`tests/fixtures/b7_regulatory/manifest.json` lists fixture ID, synthetic
source-shape note, schema/policy versions, record count, fake application IDs,
and SHA-256 values for `query_response.json`, `bulk_manifest.json`,
`bulk_partition.json.zip`, `expected.json`, and `adversarial_expectations.json`.
The fixtures remain synthetic: no copied PDF, patient, or commercial data.

Offline tests to implement (names illustrative): `test_b7_adapter_fake_transport`, `test_b7_source_validation`, `test_b7_identity_and_nested_entities`, `test_b7_dates_status_abstention`, `test_b7_provenance_and_hashes`, `test_b7_determinism`, `test_b7_scope_and_incomplete_ingestion`, `test_b7_persistence_and_escaping`, `test_b7_cli_errors_and_rollback`, `test_b7_b5_b6_non_regression`. Gates: all required fixture variants pass; all queries require explicit scope; malformed/duplicate/incomplete data produce no success artifacts; provenance is present; source record reorder gives same semantic hash; metadata-only and submission updates change respective digests; raw-only unknown fields change raw hash not semantic hash; unknown withdrawal always remains unknown; renderers agree with JSON; unchanged B6 rejects a native `b7/1.0` snapshot fail-closed as `malformed_snapshot` (exit 2 and no success artifact) and accepts old `b5`; canonical offline suite `./.venv/Scripts/python.exe -m pytest -ra -W default` passes (Windows: `.\\.venv\\Scripts\\python.exe -m pytest -ra -W default`). Historical baseline 269 passed (including 44 B6) from research checkpoint, **not** a B7 run. Optional bounded live smoke is a separate approval decision (D6), with retrieval date and observed schema/access recorded; no live test is necessary for core offline CI. No release claim without a completed source-contract check and explicit disposition of D6.

## 22. Known limitations and incremental implementation plan

Source limits: openFDA can rename fields, has disclaimer of unvalidated results, limited coverage, no record-level feed or archival guarantee, optional IDs and source-dataset-only dates. Bulk partition count may change. `application_docs.id` semantics, some codes, `search_after`, raw PDF rights, exact live ZIP payload shape, key signup and bulk authorization remain unresolved; validate actual manifest and payload in a bounded authorized smoke **before a live-source readiness claim**. If D6 approves fixture-only release, explicitly label live behavior unverified and do not claim production-source readiness. API source date cannot establish the effective date or continued market status of any specific product. Status stays `unknown` at application level.

**Risk register (proposed mitigations, not evidence that risks are resolved):**

| Risk | Impact | Proposed control / gate |
|---|---|---|
| Source schema or ZIP/manifest shape changes | Invalid or partial normalized data | Fail closed on critical shape and counts, record raw checksums; source-contract check under D6. |
| Optional/missing application or nested IDs | Missing records or ambiguous identity | Abort entire publication; no synthetic/fuzzy key; review live occurrence before locking D3. |
| Dataset timestamp mistaken for per-record change | False regulatory update claim | Keep stamp separate from semantic hash; persist observations only; future comparator requires approval. |
| Product `Discontinued` mistaken for withdrawal | Unsupported regulatory conclusion | Preserve source wording and nested scope; application status remains unknown; negative fixtures. |
| PDF copyright or licensing variance | Improper redistribution | Metadata-only; never fetch linked files; recheck terms prior to distribution under D2. |
| Source outage, key failure or interrupted bulk fetch | Partial audit and misleading success | Atomic completion marker, structured failure, no success snapshot; D6 records live access posture. |
| Hostile source content or ZIP/redirect exploit | Credential leak, unwanted fetch, unsafe report | Allowlist every redirect, bounded ZIP/JSON, escape renderers, redact auth, offline adversarial tests. |
| B5/B6 contract erosion | PubMed regressions or false PMID comparison | Separate schema/modules; unchanged full offline suite and explicit B6 rejection of `b7/1.0`. |

**Sequence after explicit MVP approval only:**

| Milestone | Objective / prerequisite | Exact scope and expected files | Tests and completion gate; risk |
|---|---|---|---|
| M0 | Approvals D1–D5 and D6 disposition; source-contract review | Review official fields and rights; if D6 chooses live verification check ZIP shape and keyed access, otherwise explicitly mark unverified; pin proposed policy versions; no new source | Review checklist signed and D6 recorded; no live readiness claim on fixture-only evidence. Risk source drift. |
| M1 | Fixtures before code; M0 | `tests/fixtures/b7_regulatory/`, `tests/test_b7_*` initial failing offline tests | Synthetic checksums and adversarial cases verified; failing tests demonstrate missing behavior. Risk overfit mitigated by independent expected results. |
| M2 | Typed validation & model; M1 | `app/models/regulatory_document.py`, `app/sources/regulatory/validation.py` | Offline parse/ZIP/identity/missing-field/security tests pass; no PubMed changes. Risk optional source fields. |
| M3 | Source adapter & normalizer; M2 | `app/sources/regulatory/fda_openfda.py`, `app/services/regulatory_normalizer.py` | Fake transport, policy pin, stable digests and nested provenance tests pass. Risk source schema drift. |
| M4 | Persistence/report & CLI; M3 | `app/services/regulatory_persistence.py`, `app/sources/regulatory/cli.py` | Read-back, escape, atomic completeness, no success artifact on error; explicit mode only. Risk partial writes. |
| M5 | Acceptance review; M4 | No new capabilities; offline full suite, bounded optional live verification per D6 | All RTM gates reviewed, source/disclaimer/terms current, B5/B6 behavior untouched; no automatic release. Risk fixture-only mismatch, disclose if live deferred. |

Future separate approval only: regulatory pairwise diff, EMA/WHO/NICE, scheduling, clinical linkage, historical archive, application status mapping. No milestone silently implements these.

## 23. Open decisions requiring approval and final approval checklist

Exact seven decisions from research §8, with recommendations, alternatives, dependencies and consequences; **all PENDING APPROVAL** (D7 explicitly deferred/non-blocking):

| ID | Decision / available alternatives | Recommendation; justification / dependency / consequence | Status |
| D1 | FDA Drugs@FDA application records only, US, metadata-only. | Approved bounded MVP scope. | APPROVED |
| D2 | Metadata/rights boundary; do not fetch third-party-copyright PDFs. | Approved; source disclaimer/terms remain retained. | APPROVED |
| D3 | `b7/1.0` schema and strict identity/version policies. | Conditionally approved against inspected source shape; material drift fails closed. | APPROVED WITH DRIFT GATE |
| D4 | No B6 extension and no cross-format comparison. | Approved; B6 production remains unchanged. | APPROVED |
| D5 | Roadmap correction and preservation of superseded history. | Approved and applied in this untracked roadmap remediation. | APPROVED |
| D6 | Keyed bounded production-adapter verification. | Recorded September 26, 2026 in a durable local attestation; reviewer acceptance remains pending. | EXECUTED; NOT INDEPENDENTLY ACCEPTED |
| D7 | EMA as a later authority. | No EMA adapter or authority activation. | DEFERRED |
| D7 | (Deferred, not blocking) Whether EMA is pre-approved as the B7.x second authority contingent on a stability/rate-limit review. | Do not pre-approve; reconsider via separate spec after EMA stability/rights review. No EMA adapter now. | PENDING APPROVAL (DEFERRED) |

**Current readiness:** product scope and implementation evidence are recorded;
D6 has a durable local attestation; fixture/offline evidence and source-contract
limitations are documented. The remaining gate is **second independent
acceptance review**, followed by separately authorized staging/commit/release
work. This is not a release claim.

**Roadmap correction proposal, NOT applied:** In `docs/PROJECT_FUTURE_ROADMAP.md` add to verification record: `2026-09-26 re-verification: HEAD 2640a76080e7b393aa5a67824cd312fc74f5c925 = annotated tag v0.6.0 (dereferenced); canonical suite 269 passed (44 B6), per B7 research checkpoint; B6 production, fixtures, tests and docs/PHASE_B6.md and docs/PHASE_B6_RTM.md present.` Change B6 phase table status `APPROVED_NEXT` → `VERIFIED_COMPLETE` and replace its stale no-commit/no-files statement with `B6 released as v0.6.0; B6 compares explicit b5 snapshots by PMID.` Replace the sentence `Phase B6 is the next approved implementation phase, not an implemented feature.` with `Phase B6 is complete and released as v0.6.0; B7 remains PROPOSED pending approval.` Under `Superseded decisions` add `2026-09-26: prior B6 APPROVED_NEXT/no implementation assertions superseded by 2640a76 and v0.6.0; historical August 2026 verification remains accurate for its original date.` Add decision-log entry `2026-09-26 | B6 complete, released v0.6.0; B7 research complete but implementation not approved | PROPOSED B7 | 2640a76, v0.6.0, B7 research package | B8+ remain separate.` Do not erase historical rows, silently rewrite old decision records, or change the roadmap's untracked state.