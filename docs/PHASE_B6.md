# Phase B6 — Longitudinal Evidence Change Detection

## B6.1 Purpose

B6 deterministically compares two persisted evidence snapshots and reports
factual state changes between them. It is a stored-snapshot comparison only.

- The caller MUST explicitly supply both snapshot inputs: one baseline
  snapshot and one target (comparison) snapshot. No implicit baseline
  selection (creation time, latest file, filename order, adjacency).
- Comparison is offline and deterministic: the same two valid snapshot
  inputs always produce semantically identical comparison output.
- B6 reports **what changed**, not **what that change means medically**.
  No clinical interpretation, recommendation, causal claim, trend
  prediction, or evidence-strength judgment beyond stored fields.
- B6 never modifies either input snapshot.

## B6.2 Terminology

- **snapshot**: persisted JSON dict from `persistence.build_snapshot`
  (schema `b5`).
- **baseline snapshot**: explicitly supplied earlier snapshot.
- **target snapshot**: explicitly supplied newer/comparison snapshot.
- **candidate / article identity**: canonical per-article match key (B6.5).
- **change**: one factual before/after difference for one entity.
- **change category**: evidence-state family (`membership`, `relevance`,
  `study`, `review`, `integrity`, `extraction`, `ranking`, `placement`,
  `comparability`).
- **change type**: precise transition within a category.
- **priority**: deterministic workflow-ordering rank, no clinical meaning.
- **audit record**: the `meta` block reproducing the comparison.
- **snapshot schema version**: stored `schema_version` (`b5`).
- **comparison schema version**: `b6/1.0`.
- **comparability**: deterministic statement of whether snapshot collection
  scope can be verified before evidence-state differences are interpreted.

## B6.3 Inputs

`compare_snapshots(baseline, target, compared_at)` takes two loaded
snapshot dicts plus an audit-only ISO-8601 timestamp string that MUST NOT
affect semantic equality or change ordering.

The module CLI `python -m app.services.evidence_diff BASELINE TARGET`
requires two explicit snapshot file paths. No default baseline, no
directory scan, no "latest" heuristic. File loading is separated from the
pure semantic comparison.

## B6.4 Determinism contract

- Identity matching by canonical PMID (stripped string); no fuzzy match.
- Fixed field sets and change vocabulary per category (B6.7).
- Changes sorted by `(priority, category, change_type, pmid, field_path)`.
- Canonical JSON uses `sort_keys=True`; snapshot/comparison identities are
  SHA-256 of canonical bytes. Raw `baseline_snapshot_id` and
  `target_snapshot_id` preserve complete input provenance. Normalized semantic
  snapshot IDs remove audit-only timestamps and candidate-set order and are
  used by `comparison_id`, so those audit-only variations do not change the
  comparison identity.
- `change_id` is sha256 hex (first 16) of the canonical encoding of
  `(category, change_type, pmid, field_path, baseline_present,
  baseline_value, target_present, target_value)`.
- `fetched_at`, `assessed_at`, `compared_at` are audit-only, never compared.
- Order-insensitive lists compare as multisets of canonical encodings.
- String comparison is exact (no case folding or whitespace collapsing).
- Absent key, explicit `null`, empty collection, and empty string are
  distinct; before/after values use `{"present": bool, "value": ...}`.

## B6.4a Snapshot comparability (`comparability_policy_version = "1.0"`)

`topic` identifies the stored evidence collection. B6 does not infer topic
equivalence from title words, query similarity, article overlap, embeddings,
or array position.

- Two non-empty string topics are normalized by trimming outer whitespace and
  must then be exactly equal to compare. Distinct normalized topics fail
  closed with `ComparisonError(code="incomparable_snapshots")`.
- A missing, non-string, or whitespace-only topic does not prove the two
  collections are different. B6 continues, records `scope` as
  `topic_unavailable` or `topic_partially_unavailable`, and emits one
  priority-8 `comparability/scope_unverifiable` change.
- `query` is provenance for a search strategy, not an identity. When both
  stored queries are strings and differ, B6 continues and emits one
  priority-8 `comparability/query_changed` factual change. When either query
  is unavailable, the audit status records that fact without guessing.
- `meta.comparability` includes this policy version, scope, topic/query
  availability, `query_changed`, and `identical_content`. Identical input
  content is a documented zero-change no-op.
## B6.5 Identity policy (`article_identity_policy_version = "1.0"`)

PMID is the primary and only article identity. B5's normalizer stores
`pmid` as a string that may be empty when PubMed supplied no PMID, so B6
MUST NOT assume PMID is present or unique. No secondary identifier (DOI,
title) is ever used for matching.

Duplicate PMID: a snapshot with two records sharing one canonical
(stripped, non-empty) PMID is an integrity error. Comparison fails closed
with `ComparisonError(code="duplicate_pmid")` naming role and PMID. No
silent first-wins, last-wins, merge, or discard.

Missing PMID: a record with missing/empty PMID has no stable identity and
is excluded from pairwise comparison (never matched by title, DOI, or
position). It is listed in `meta.unmatched_records` with a deterministic
truncated `record_digest`, digest-scoped `occurrence`, and `unmatched_count`
in the summary. Audit records are sorted by snapshot role and digest;
repeated identical missing-PMID records remain separately represented but are
never matched.

## B6.6 Version compatibility (`snapshot_compat_policy_version = "1.0"`)

Supported snapshot `schema_version`: `{"b5"}` only. Missing, non-string,
or unknown versions (incl. `legacy`) on either side fail closed with
`ComparisonError(code="unsupported_schema_version")` naming the side(s).
Malformed input fails with `code="malformed_snapshot"`. B6 never migrates
snapshots.

## B6.7 Change model (`comparison_schema_version = "b6/1.0"`)

One canonical result dict; Markdown and HTML render it, adding no facts.
Change fields: `change_id`, `category`, `change_type`, `pmid`,
`field_path`, `baseline`/`target` as `{"present", "value"}`, `priority`,
`description`, `detail`.

Per-article state (present on both sides only):

- membership: `added` / `removed`. `removed` means only "absent from the
  target set", never "retracted" or "invalid".
- relevance: `clinical_relevance.{relevance_class, decision,
  relevance_score}` -> `relevance_changed`.
- study: `study_assessment.{design_family, design_subtype}` ->
  `study_design_changed`; `{result_status, evidence_tier}` ->
  `study_result_changed`. Field comparison is skipped if either side lacks
  `assessment.study_assessment`.
- review: change in any relevance/study/integrity/extraction `needs_review`
  source, including a source handoff that keeps the aggregate requirement
  true, -> `review_required_changed` with per-source detail.
- integrity: `publication_integrity.{status, record_role,
  final_decision, report_eligible}` -> `integrity_changed`.
- extraction: recursive diff of `structured_clinical_extraction`:
  `extraction_added` / `extraction_removed` / `extraction_changed`,
  refined to abstention transitions when one side is `null`, `""`,
  `not_reported`, `not_extractable`, `not_applicable`, `unclear`,
  `unknown`, or empty list; `extraction_provenance_only` when the leaf
  path passes through `provenance`/`warnings`. Dict lists compare as
  multisets of canonical encodings.
- ranking: `final_evidence_rank` -> `rank_changed` with
  `detail.candidate_set_changed` distinguishing membership-driven shifts.
- placement: `report_placement.{section, visible, display_mode}` ->
  `placement_changed`, or `became_key_evidence` when target section is
  `key_evidence` and baseline was not.
- persisted block availability: B5 may intentionally set `assessment` and
  `final_evidence_rank` to `null` and omit
  `structured_clinical_extraction` for an integrity-excluded candidate. For
  `clinical_relevance`, `assessment`, `assessment.study_assessment`,
  `publication_integrity`, `structured_clinical_extraction`,
  `final_evidence_rank`, and `report_placement`, B6 emits priority-8
  comparability records when availability changes:
  `block_became_comparable`, `block_became_not_comparable`, or
  `block_state_changed`. `absent`, explicit `null`, `present`, and invalid
  persisted block types remain distinct. B6 does not fabricate detailed
  study/extraction/ranking differences across an unavailable block.

## B6.8 Priority (`comparison_priority_policy_version = "1.0"`)

Workflow review order only: 1 integrity; 2 membership; 3 relevance;
4 study; 5 material extraction; 6 review; 7 ranking, placement,
provenance-only; 8 comparability. Ties break by `(category,
change_type, pmid, field_path)`.

## B6.9 Auditability

`meta` holds policy/schema versions (including `comparability_policy_version`), raw
`baseline_snapshot_id` and `target_snapshot_id` (SHA-256 of canonical input
bytes), normalized `baseline_semantic_snapshot_id` and
`target_semantic_snapshot_id`, input
`topic`/`query`/`fetched_at`, `comparison_id`, `compared_at`,
per-category `counts`, `total_changes`, `unmatched_records`. No secrets
or local paths.

## B6.10 Wording

OK: "relevance changed from X to Y", "rank changed from 4 to 2".
Banned: stronger/safer/confirmed, confidence increased, treatment
preference, causal or predictive claims.

## B6.11 Outputs

Canonical JSON plus Markdown/HTML from `render_markdown_comparison` /
`render_html_comparison`. HTML is standalone (inline CSS, no JS, no
external deps, escaped text); Markdown also HTML-escapes dynamic stored text.
Filenames:
`<base>_vs_<target>.comparison.{json,md,html}`.

## B6.12 Errors

`ComparisonError.code`: `snapshot_not_found`, `snapshot_unreadable`,
`malformed_snapshot`, `unsupported_schema_version`, `duplicate_pmid`,
`incomparable_snapshots`.
Fail closed; no tracebacks in output.

## B6.13 B5 compatibility

B6 is additive; no B5 field, default, or behavior changes.
