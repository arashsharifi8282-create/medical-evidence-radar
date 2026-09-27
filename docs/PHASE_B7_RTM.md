# Phase B7 — Proposed Requirements Traceability Matrix

## Active remediation reconciliation (2026-09-26)

**Review state:** the first independent acceptance review was **REJECTED /
BLOCKED**. It found no production-code defect and independently ran 374/374
canonical tests, but rejected acceptance because its D6 process execution could
not be reconstructed from durable evidence and B7 documentation still contained
contradictory proposal-era status claims. The second independent acceptance
review concluded **ACCEPTED — READY FOR RELEASE PREPARATION** (F1–F4
resolved, R01–R25 PASS, D6 attestation accepted; independently executed 109
focused B7 and 378 canonical tests, 5/5 fixture checksums matched). The
remediation record below is retained as history; the release commit records
the second-review acceptance. GitHub publication is verified separately.

**Implementation-agent evidence:** the test-first history and completed offline
suite below are implementation evidence. They do not substitute for second
independent acceptance review.

Evidence: test-first behavioral red run 14 failures (11 persisted corruptions accepted,
missing provenance and two unhandled manifest count types); later red runs caught
unvalidated mapped-value/path mutations, credential-bearing source URLs, duplicate
JSON keys, depth/count bound and bad-type exceptions. Later red/green coverage added
completion-marker checksums, marker-last interruption recovery, total elapsed
deadlines, structured HTML document-link metadata, credential aliases and an
independently authored adverse-case catalogue. A fixture-file missing failure was
setup evidence, not a behavioral red test.
Historical implementation-agent baseline: 105 focused B7, 161 B7+B5/B6-focused
(56 unchanged B5/B6), and 374 canonical offline; five fixture checksums matched
and `git diff --check` was clean. These completed offline tests are distinct
from the later D6 keyed production smoke. Native B7
rejection is checked through the unchanged B6 CLI against the saved B7 JSON:
exit 2, `malformed_snapshot`, no B6 success outputs. No `articles` was added.

**R18 approved acceptance contract:** "Native b7/1.0 snapshots must be
rejected fail-closed by the unchanged B6 comparator; the current
`malformed_snapshot` code is accepted and documented." Native B7 has no B6
`articles` list, so unchanged B6 performs the shape check before version
validation. No `articles` field is inserted and B6 production code remains
unchanged.

**Raw retention:** approved §9 permits checksum-only loss if explicitly
audited. `audit.warnings` records that raw bytes are not retained;
raw record and response/manifest checksums remain, and recognized nested
`source_fields` retain source values and paths. Unknown values and full raw
record bytes cannot be reconstructed from the snapshot. Field-level provenance
is not claimed for unknown fields; authenticity of retained mapping cannot be
proven without independent source bytes.

**R12 disposition:** PASS against the approved digest-plus-disclosure policy.
Supported normalized fields retain value-state/value/path provenance, nested
field paths are validated against the canonical record shape, and mapped-value,
identity, raw/reference and semantic-digest mutations fail closed. Query
response and record digests, or bulk manifest/partition and record digests,
remain available. Full raw bytes and unknown fields are intentionally not
reconstructable; this is disclosed in `audit.warnings`, not silently inferred.
Any requirement for raw reconstruction would be a stronger, separately
approved versioned retention/schema contract.

**R24 disposition:** PASS for the approved deterministic boundary. Before
network access, query scope rejects credential-bearing parameter forms,
explicit patient-identifier fields, recognizable email/SSN/phone literals and
control characters while allowing ordinary biomedical openFDA syntax. Snapshot
validation reapplies the policy before persistence. Redirect, endpoint and
source-link checks prevent credential-bearing URLs; stable errors and rendered
artifacts do not contain the transport key. This is not a claim that arbitrary
free text can be comprehensively classified as sensitive.

**D3 source gate:** verified on one 2026-09-26 export: manifest partition
shape, observed product/submission keys, date formats and lack of application
status/per-record version. Accepted policy: exact IDs, fail on missing/duplicate
keys, no status promotion, digest-only raw loss. Unverified: future exports,
codes, comprehensive source semantics or downstream PDF rights. Material
identity/field/schema changes require approval and a versioned contract;
none were silently introduced by remediation. **New durable D6 evidence:** a
controlled September 26, 2026 Windows child invocation now has a local
`b7-d6-attestation/1.0`: key-present boolean only, actual child exit `0`,
`application_number:NDA020123`, limit `1`, no PDF/link retrieval, one
FDA/openFDA/US `drug_application` record, semantic/artifact SHA-256 values,
completion-marker and JSON/Markdown/HTML consistency verification, and passed
credential-redaction checks. The CLI exposes no raw HTTP status, so none is
claimed. See `PHASE_B7_D6_ATTESTATION_CONTRACT.md` and the M0 record.

Product decisions: D1 FDA-only, D2 metadata/rights boundary, D4 B5/B6 separation,
D5 roadmap correction approved; D3 checked against current official bulk
export (see `PHASE_B7_M0_SOURCE_CONTRACT.md`) with fail-closed drift; D7 deferred.
D6 is **executed with durable local evidence; independent acceptance pending**.
Historical rows that follow remain the original proposed plan, not current PASS
claims. `tests/test_b7_*` means both
`tests/test_b7_regulatory.py` and `tests/test_b7_adapter.py`.

| Requirement | Actual implementation | Supporting executed test / acceptance condition | Verification result and limitation |
|---|---|---|---|
| B7-R01 | `app/sources/regulatory/cli.py`, `fda_openfda.py` | `test_b7_cli_rejects_other_authorities_without_network`, `test_b7_cli_query_mode_offline`; explicit source/mode | PASS offline; no default retrieval |
| B7-R02 | `app/services/regulatory_normalizer.py` | `test_b7_normalization_scope_status_and_provenance`; records explicitly US | PASS offline; US is source scope only |
| B7-R03 | `fda_openfda.py`, `validation.py`; `run_b7_d6_attestation.py` | Offline key/redirect/URL tests; D6 durable attestation of bounded keyed CLI smoke | IMPLEMENTATION PASS / DURABLE LOCAL D6 EVIDENCE: limit-1 `NDA020123` child exit 0; no PDFs or linked documents. Independent acceptance pending. |
| B7-R04 | `regulatory_persistence.py`, `fda_openfda.py` | `test_b7_query_fake_transport_and_explicit_key`, `test_b7_two_partitions_complete_and_source_locators`, `test_b7_renderers_and_b6_rejection`; dataset-only fake requests and source credit | PASS offline: no PDF requests; external PDF rights are explicitly excluded rather than cleared for reuse |
| B7-R05 | `fda_openfda.py`, `validation.py` | `test_b7_two_partitions_complete_and_source_locators`, `test_b7_inconsistent_partition_metadata_no_publish`, `test_b7_bulk_corrupt_or_incomplete_never_publishes`, `test_b7_boolean_one_record_partition_count_is_not_integer` (behavioral red then green); complete fake manifest | PASS offline for tested manifest/partition integrity; real keyed smoke separately blocked under R22; process-crash atomicity remains R17 |
| B7-R06 | `validation.py`, `regulatory_normalizer.py` | `test_b7_adversarial_nested_source`, `test_b7_optional_absent_null_empty_and_unknown_status`, `test_b7_invalid_records_fail_closed` | PASS offline for tested types, arrays, nullable/empty and date cases; depth/count caps are tested separately under R16 |
| B7-R07 | `regulatory_normalizer.py`, `regulatory_persistence.py` | `test_b7_persisted_schema_rejects_nested_corruption`, `test_b7_persisted_top_level_state_and_container_provenance_are_consistent`, `test_b7_persisted_duplicate_json_keys_fail_closed`; exact key sets, mapped nested values/paths, container states and semantic digest | PASS offline for the serialized `b7/1.0` boundary; field authenticity and unknown-field reconstruction remain explicitly outside the retained digest-only raw policy (R12/R25) |
| B7-R08 | `regulatory_normalizer.py` | `test_b7_invalid_records_fail_closed`; missing/duplicate application ID rejected | PASS offline; current export M0 identity check only |
| B7-R09 | `regulatory_normalizer.py` | `test_b7_duplicate_nested_ids_and_unknown_doc_id`, `test_b7_adversarial_nested_source`; missing product and both submission keys rejected; duplicate links retained | PASS offline for nested identity/multiplicity |
| B7-R10 | `validation.py`, `regulatory_normalizer.py` | `test_b7_invalid_records_fail_closed`, `test_b7_normalization_scope_status_and_provenance`; Gregorian date/unknown publication | PASS offline for tested cases; no regulatory effective-date inference |
| B7-R11 | `regulatory_normalizer.py`, `regulatory_persistence.py` | `test_b7_normalization_scope_status_and_provenance`, `test_b7_optional_absent_null_empty_and_unknown_status`; Discontinued product only, unmapped codes trigger review | PASS offline; application status remains unknown |
| B7-R12 | `regulatory_normalizer.py`, `regulatory_persistence.py` | `test_b7_nested_provenance_and_raw_loss`, `test_b7_persisted_schema_rejects_nested_corruption`, `test_b7_persisted_top_level_state_and_container_provenance_are_consistent`; mapped nested paths/raw values, states and record digest | PASS under the approved digest-plus-disclosure policy: retained mappings are cross-checked; discarded raw bytes and unknown fields cannot be reconstructed or independently authenticated, and that limitation is explicit rather than silently inferred |
| B7-R13 | `fda_openfda.py`, `regulatory_normalizer.py`; `run_b7_d6_attestation.py` | Offline retrieval/provenance tests; durable D6 snapshot/reload/semantic digest/artifact-digest checks | IMPLEMENTATION PASS / DURABLE LOCAL D6 EVIDENCE: FDA/openFDA/US, `b7/1.0`, query metadata, one record, and completion-marked projections verified. Dataset stamp is not record version; independent acceptance pending. |
| B7-R14 | `regulatory_normalizer.py` | `test_b7_semantic_reordering_raw_only_and_dataset_timestamp`, `test_b7_semantic_hash_nested_reordering_and_changes`, `test_b7_canonical_nested_permutations_byte_equivalent_semantics`, `test_b7_same_name_different_strength_ingredient_order_is_semantic_invariant` (behavioral red then green); canonical output stable on repeat | PASS for tested permutations; raw locators and raw digests intentionally differ |
| B7-R15 | `regulatory_normalizer.py` | `test_b7_semantic_reordering_raw_only_and_dataset_timestamp`, `test_b7_bulk_fake_transport_end_to_end`; no comparator | PASS offline; no deletion/withdrawal inference |
| B7-R16 | `validation.py`, `fda_openfda.py`, `regulatory_persistence.py` | `test_b7_zip_symlink_and_bomb_rejected`, `test_b7_json_depth_and_object_count_bounds`, `test_b7_total_elapsed_deadline_rejects_slow_stream`, `test_b7_additional_credential_aliases_and_multi_member_archives_fail_closed`, `test_b7_unsafe_urls`, renderer escaping tests | PASS offline for calibrated bounds: one ZIP member, 40 MB ZIP, 200 MB JSON/response, depth 100, 10,000,000 nodes, 180 s query and 1,800 s bulk deadlines; limits are documented historical calibrations, not future-source guarantees |
| B7-R17 | `validation.py`, `regulatory_persistence.py`, `cli.py` | `test_b7_write_failure_rolls_back`, `test_b7_bulk_corrupt_or_incomplete_never_publishes`, `test_b7_interrupted_query_no_artifact`, `test_b7_reader_refuses_interrupted_and_modified_publications`, `test_b7_completion_marker_last_and_recovery_after_interrupted_marker`; exit 2/no complete marker | PASS offline: artifacts are temp-written and fsynced where supported; JSON/MD/HTML publish before a checksummed marker; readers reject missing/corrupt/tampered generations and marker-less crash residue is removed before republish. Cross-process/filesystem crash guarantees remain limited to the documented atomic-replace semantics. |
| B7-R18 | independent B7 modules; B5/B6 untouched | `test_b7_native_b6_rejection_fails_closed_with_shape_error`, `test_b7_native_b6_cli_no_success_artifacts`; B5/B6 regression subset | PASS: unchanged B6 rejects native B7 fail-closed as `malformed_snapshot` because it has no `articles` list; CLI exit 2 and no B6 success artifact. No synthetic `articles` field was inserted and no B6 production code was modified. |
| B7-R19 | `regulatory_persistence.py` | `test_b7_rendered_counts_ids_statuses_match_json`, `test_b7_html_has_independent_structured_metadata_and_exact_doc_link_text`, `test_b7_reader_refuses_interrupted_and_modified_publications`; source-faithful counts, IDs, status wording, product/submission and document-link metadata | PASS offline: Markdown and independently structured escaped HTML project the same audited JSON; links remain displayed as text-only metadata and are never fetched or presented as approvals |
| B7-R20 | checksummed `tests/fixtures/b7_regulatory/`, `tests/test_b7_*` | `test_b7_fixture_checksums`, `test_b7_checksummed_bulk_fixture_roundtrip`, adverse red/green probes; five fixture checksums including `adversarial_expectations.json` | PASS offline: checksummed synthetic positive fixtures plus an independently authored eight-case adverse expected-code catalogue; 93 focused B7, 149 B7+B5/B6-focused and 362 canonical tests pass |
| B7-R21 | `cli.py`, B6 unchanged | `test_b7_cli_rejects_other_authorities_without_network`, `test_b7_native_b6_cli_no_success_artifacts`; no cross-format comparison | PASS offline for the authority/isolation boundary; R18's accepted native-B7 rejection is independently PASS |
| B7-R22 | M0 source contract and D6 attestation contract | Historical source/terms/shape review plus one controlled keyed D6 attestation | IMPLEMENTATION PASS / LIVE-SOURCE READINESS EVIDENCE: D3 review and D6 local observation are recorded; future drift and continuing access are not guaranteed; independent acceptance pending. |
| B7-R23 | `docs/PROJECT_FUTURE_ROADMAP.md` | untracked-roadmap preservation and status reconciliation | IMPLEMENTATION PASS: history preserved; approved scope, uncommitted/unreleased state, and pending second review are distinguished. Independent acceptance pending. |
| B7-R24 | `fda_openfda.py`, `regulatory_persistence.py` | `test_b7_query_secret_or_obvious_patient_scope_rejected_before_request`, `test_b7_source_auth_urls_never_persist`, `test_b7_additional_credential_aliases_and_multi_member_archives_fail_closed`, `test_b7_query_source_key_does_not_persist_in_renderers`; errors constant | PASS for the approved deterministic filter and redaction boundary: tested credential aliases and obvious patient predicates are rejected before requests and source-link credentials never persist. It remains explicit that arbitrary sensitive free text cannot be comprehensively classified. |
| B7-R25 | `regulatory_normalizer.py` | `test_b7_nested_provenance_and_raw_loss`, `test_b7_semantic_reordering_raw_only_and_dataset_timestamp`; explicit loss warning and raw-only hash difference | PASS for §9 alternative loss policy; no claim to reconstruct unknown raw values |

**Active disposition:** implementation-agent evidence supports the approved,
limited B7 contract; R03/R13/R22 now include durable local D6 evidence and R23
has reconciled roadmap state. R18 remains PASS under the approved unchanged-B6
native-`b7/1.0` fail-closed `malformed_snapshot` contract. **The first
independent review remains rejected/blocked, and second independent acceptance
is pending.** This does not guarantee future source stability, expand raw
retention, activate future authorities, or release B7.

## Historical proposal RTM (superseded status language retained for provenance)

The rows below are the original pre-implementation proposal. Their
`proposed`/pending wording is historical and must not be read as the active
implementation or review state.

| Req ID | Requirement | Justification / source | Spec | Proposed implementation | Required test (planned, offline) | Acceptance condition | Approval status |
|---|---|---|---|---|---|---|---|
| B7-R01 | FDA Drugs@FDA only; explicit query or bulk; no default retrieval; reject other endpoints | Research §§4.1,5; roadmap B7 scope gate | §§3–5,8 | `app/sources/regulatory/cli.py`, `fda_openfda.py` | `test_b7_source_and_explicit_scope` | Only allowlisted authority/category/mode; invalid input exit 2, no success artifact | proposed; D1 PENDING APPROVAL |
| B7-R02 | US source jurisdiction retained, not global clinical applicability | Research §§4.1,5; `AGENTS.md` | §§6,9,13,15 | `app/models/regulatory_document.py`, `regulatory_normalizer.py` | `test_b7_jurisdiction_and_abstention` | Every record explicitly US and no cross-jurisdiction claim | proposed; D1 PENDING APPROVAL |
| B7-R03 | Documented HTTPS endpoint, keyed query and manifest-listed ZIP only; bound search pagination | Research §4.1; FDA access docs | §§7,8,18 | `fda_openfda.py`, `validation.py` | `test_b7_adapter_fake_transport` | URL/path/redirect/timeouts and limit checks; no `search_after` dependency | proposed; D1/D6 PENDING APPROVAL |
| B7-R04 | Respect licensing warnings; metadata-only and never fetch linked PDFs; display source credit/disclaimer | Research §§4.1,5; openFDA terms | §§5,7,13,18,20 | `fda_openfda.py`, `regulatory_persistence.py` | `test_b7_no_pdf_fetch_and_terms` | Zero document-URL requests; snapshots/reports show disclaimer and credit | proposed; D2 PENDING APPROVAL |
| B7-R05 | Validate complete manifest and every partition before publishing a bulk observation | Research §§4.1,6; no record feed | §§7,8,14,16 | `validation.py`, `regulatory_persistence.py` | `test_b7_bulk_partition_count_and_interruption` | Missing/extra/partial/corrupt partition fails with no success artifact | proposed; D1/D3 PENDING APPROVAL |
| B7-R06 | Validate top-level envelope, records, nested arrays, IDs, dates and types without coercion | Research §§4.1,6 | §§8–12,16 | `validation.py`, `regulatory_normalizer.py` | `test_b7_source_validation` | Malformed/unknown critical shape rejected; optional absent/null/empty preserved | proposed; D3 PENDING APPROVAL |
| B7-R07 | Persist strict `b7/1.0` record and snapshot with pinned normalization/identity/version/status policy versions | Research §6.2; B5/B6 schemas | §§9–12,19 | `app/models/regulatory_document.py`, `regulatory_normalizer.py`, `regulatory_persistence.py` | `test_b7_schema_roundtrip_and_unsupported_versions` | Every required field typed; unknown snapshot version rejected; round-trip preserves meaning | proposed; D3 PENDING APPROVAL |
| B7-R08 | Exact `(FDA,drug_application,application_number)` identity; reject missing and duplicate IDs without fallback or synthetic PMID | Research §§4.1,6.3; B6 PMID-only | §§9–10,19 | `regulatory_normalizer.py`, `validation.py` | `test_b7_identity_missing_duplicate` | Same source ID stable; missing/duplicate fails entire publish | proposed; D3/D4 PENDING APPROVAL |
| B7-R09 | Separate keyed submissions/products, preserve multiples and never assume `application_docs.id` is unique | Research §§4.1,6.2–3; document-ID type ambiguity | §§9–10 | `app/models/regulatory_document.py`, `regulatory_normalizer.py` | `test_b7_nested_identity_and_multiplicity` | No loss/reassignment; missing/duplicate nested keys rejected; documents retained without fabricated identity | proposed; D3 PENDING APPROVAL |
| B7-R10 | Source dates only at their true level; YYYYMMDD calendar validation; no invented publication/effective dates | Research §4.1 | §§9,11–13 | `regulatory_normalizer.py` | `test_b7_dates_and_invalid_timestamps` | Invalid supplied date fails; missing stays null; source stamp never called record update | proposed; D3 PENDING APPROVAL |
| B7-R11 | Application status unknown unless explicit verified mapping; product marketing status retained verbatim; `Discontinued` not withdrawal | Research §§4.1,6; safety boundary | §§9,11–15 | `regulatory_normalizer.py`, `regulatory_persistence.py` | `test_b7_status_abstention_and_unknown_withdrawal` | Unsupported codes flagged; no regulatory/clinical conclusion from source presence | proposed; D3 PENDING APPROVAL |
| B7-R12 | Field-level provenance for normalized sourced fields and versioned derivations; raw exact checksum and source locator | Research §6.2, `AGENTS.md` | §§9,12–14 | `regulatory_normalizer.py`, `regulatory_persistence.py` | `test_b7_field_provenance_and_raw_checksum` | Each mapped field reconstructible from retained raw fixture; no secret/path leaks; unknown raw-only change visible by hash | proposed; D3 PENDING APPROVAL |
| B7-R13 | UTC retrieval metadata, dataset timestamp kind, completeness/scope/partition audit and integrity digests | Research §§4.1,6; B6 audit precedent | §§9,11,13–14 | `fda_openfda.py`, `regulatory_persistence.py` | `test_b7_retrieval_audit_and_counts` | Explicit scope/count/time/version/hashes on every successful snapshot | proposed; D3 PENDING APPROVAL |
| B7-R14 | Deterministic normalization, sorting, canonical hashes; raw/audit changes separate from semantic changes | Research §6.3; B6 determinism contract | §§11–12,17 | `regulatory_normalizer.py`, `regulatory_persistence.py` | `test_b7_reordering_digest_and_serialization` | Reordered inputs yield same semantic digest; raw-only changes retain distinct raw hash; same input byte-identical serialized semantic form | proposed; D3 PENDING APPROVAL |
| B7-R15 | No invented record-level feed, withdrawal or deletion; distinguish candidate-set changes and dataset refresh from source state | Research §§4.1,6; B6 removal boundary | §§11,14 | `regulatory_normalizer.py` (observation only) | `test_b7_scope_and_dataset_refresh_metadata` | Snapshot accurately labels bounded vs complete; no pairwise change engine claimed/created | proposed; D3/D4 PENDING APPROVAL |
| B7-R16 | Untrusted input/URL/ZIP/redirect bounds and HTML/Markdown escaping; no source-content execution | `AGENTS.md`; source-data threat model | §§16,18 | `validation.py`, `fda_openfda.py`, `regulatory_persistence.py` | `test_b7_security_and_escaping` | Unsafe redirects/traversal/oversize rejected; hostile text escaped; zero outbound linked URL fetch | proposed; D1–D3 PENDING APPROVAL |
| B7-R17 | Structured failure codes, no success artifacts on invalid/partial retrieval, corrupt input or interrupted write | B6 error precedent; research §6 | §§14,16,18 | `validation.py`, `regulatory_persistence.py`, `cli.py` | `test_b7_error_codes_and_atomic_rollback` | Stable code and CLI exit 2, secrets redacted, complete marker not written | proposed; D3 PENDING APPROVAL |
| B7-R18 | Independent B7 directories/CLI/models; B5/B6 paths and code untouched | `persistence.py`, `evidence_diff.py`; research §6 | §§8,19–20 | New B7 modules only | `test_b7_b5_b6_non_regression` | Existing B5 build/render unchanged; B6 b5 compare unchanged and b7 rejected | proposed; D4 PENDING APPROVAL |
| B7-R19 | JSON/Markdown/HTML projections consistent, source-faithful, audit-linked, no product approval presentation | B5/B6 renderer conventions; openFDA disclaimer | §§2,8,13,17,21 | `regulatory_persistence.py` | `test_b7_renderers_agree_with_json` | Identical record counts/IDs/status wording, no fabricated content, safe HTML | proposed; D2/D3 PENDING APPROVAL |
| B7-R20 | Synthetic checksummed offline fixtures and red-test-first implementation, followed by full unchanged regression suite | Research §§1,6; B5 fixtures | §§21–22 | `tests/fixtures/b7_regulatory/`, `tests/test_b7_*` | `test_b7_fixture_checksums`, full pytest | All adverse and positive cases pass offline; original 269-test baseline not degraded | proposed; D1–D5 PENDING APPROVAL |
| B7-R21 | Additional authority never silently activated; no universal status or cross-format comparison | Research §§5–6; report-policy reserved list | §§15,19–20,23 | `cli.py` allowlist, no change to B6/config | `test_b7_other_authority_rejected` | EMA/WHO/NICE inputs rejected; B6 rejects `b7/1.0` | proposed; D4/D7 PENDING APPROVAL |
| B7-R22 | Live source and license readiness gate records key disposition; fixture-only release labeled unverified | Research §8 question 6; source drift | §§7,21–23 | Acceptance review (no CI network dependency) | documented bounded smoke or documented deferral | Source terms/access/ZIP shape reviewed before production-readiness sign-off; no false live validation claim | proposed; D6 PENDING APPROVAL |
| B7-R23 | Do not modify the untracked future roadmap without separate authorization; preserve superseded decisions | Research §§1,7–8; roadmap §10 | §23 | Documentation-only approval process | final git-status and diff review | Roadmap unchanged during specification; exact suggested edits supplied | proposed; D5 PENDING APPROVAL |
| B7-R24 | Never persist API credentials, request auth URLs, patient data or untrusted source instructions | Research §6.7; `AGENTS.md` | §§13,16,18 | `fda_openfda.py`, `regulatory_persistence.py` | `test_b7_secret_redaction_and_untrusted_data` | No secrets in logs/JSON/MD/HTML/error; untrusted data only data | proposed; D1–D3/D6 PENDING APPROVAL |
| B7-R25 | Keep raw records accessible locally with digests or explicitly audit any loss; do not assert unknown fields are field-level mapped | Research §6.5; openFDA schema evolution | §§9,11–13,21 | `validation.py`, `regulatory_persistence.py` | `test_b7_unknown_field_raw_only_change` | Unknown-field change detectable by raw digest; documented retention/loss; no invented mapping | proposed; D3 PENDING APPROVAL |

**Historical proposal workflow (not started at proposal time):** synthetic
fixtures and checksums → failing offline tests → minimal adapter/model/
normalizer → focused tests → canonical full regression suite → human
source-contract/approval review. No test in this historical matrix currently
passes *as a B7 test*. D7 is a non-blocking later-authority question; D1–D5 and
D6 disposition gate the proposed FDA MVP. Pairwise B7 change reporting and
EMA/WHO/NICE requirements are **future contracts**, not acceptance criteria for
the B7 MVP.