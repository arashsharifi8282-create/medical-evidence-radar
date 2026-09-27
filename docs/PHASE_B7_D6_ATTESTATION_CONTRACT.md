# Phase B7 D6 — Controlled execution-attestation contract

**Status: operational audit contract for B7 release v0.7.0.** The second
independent acceptance review concluded **ACCEPTED — READY FOR RELEASE
PREPARATION** and accepted this D6 attestation approach. This contract does
not prove historical FDA server behavior; remote GitHub publication is
verified separately after push.

## Purpose and boundary

A D6 execution attestation is a durable, local observation of one controlled
Windows child process and the B7 artifacts it generated. It closes the earlier
auditability gap by preserving the observed child exit status and independently
reloading the completion-marked publication. It is **not** a cryptographic proof
of what an FDA server returned at a past time.

The helper is `scripts/run_b7_d6_attestation.py`. It invokes exactly one
production CLI child using only this approved bounded scope:

- source: `fda-drugsfda`;
- query: `application_number:NDA020123`;
- limit: `1`;
- `--save` with caller-supplied dedicated local data/report directories;
- no PDF or linked-document retrieval.

It suppresses child stdout/stderr rather than retaining raw output. The B7 CLI
continues to own retrieval, normalization, and persistence behavior.

## Required attestation fields

The serialized `b7-d6-attestation/1.0` JSON contains only:

- UTC execution start and finish timestamps;
- bounded command identity and scope;
- `environment_openfda_api_key_present` boolean only;
- actual child `process_exit_code` (or `null` when no child was started);
- safe outcome classification (`success`, `environment_missing`, `cli_failed`,
  `process_start_failed`, `process_timeout`, or
  `post_execution_validation_failed`);
- FDA/openFDA source, jurisdiction, document type, schema, retrieval method,
  approved endpoint, and dataset timestamp identity;
- normalized record count, expected application identity, semantic snapshot
  digest, and retained raw-response digest;
- SHA-256 values for generated JSON, Markdown, and HTML;
- completion-marker and JSON/Markdown/HTML consistency outcomes; and
- exact-credential-absence and credential-marker-redaction outcomes.

For a successful controlled D6 run, post-execution validation uses the existing
`load_published_snapshot` contract and requires `b7/1.0`, FDA/openFDA/US
`drug_application`, query retrieval, `NDA020123`, and all three count fields
equal to one. It does not claim a raw HTTP status because the CLI does not
expose one safely.

## Explicitly prohibited retention

The attestation, its helper, and release-candidate documentation must never
retain or display an API key (or its hash), authorization header,
credential-bearing URL, raw unsanitized stdout/stderr, patient-specific data,
or full FDA response bytes. The API key is read only in memory for a boolean
presence check and exact in-memory artifact scan. The B7 retention policy stays
digest-plus-disclosure; this contract does not authorize raw-source retention.

## Local location and reviewer interpretation

Attestations are generated under the ignored dedicated D6 report directory,
beside the completion marker, and are local audit output rather than release
content. An independent reviewer can evaluate the stated local observation,
artifact integrity, and documented limitations, but must not infer continuing
source availability, future schema stability, server-side authentication state,
or regulatory meaning from it.