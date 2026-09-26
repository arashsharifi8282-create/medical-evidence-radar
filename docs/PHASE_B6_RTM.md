# Phase B6 — Requirements Traceability Matrix

One row per B6 requirement: spec section, implementation, test(s), status.

| Req ID | Requirement | Spec | Implementation | Test(s) | Status |
|---|---|---|---|---|---|
| B6-R01 | Explicit baseline selection enforced | PHASE_B6 B6.3 | `evidence_diff.main`, `load_snapshot_file` | `test_load_snapshot_file_errors_are_structured` | pass |
| B6-R02 | Explicit target selection enforced | PHASE_B6 B6.3 | `evidence_diff.main` (two required positionals) | CLI smoke (below) | pass |
| B6-R03 | Deterministic output | PHASE_B6 B6.4 | `compare_snapshots`, `_canonical`, sort keys | `test_determinism_under_reordering_and_repetition` | pass |
| B6-R04 | Duplicate PMID fails closed | PHASE_B6 B6.5 | `_index` | `test_duplicate_pmid_fails_closed` | pass |
| B6-R05 | Missing PMID unmatched, never fuzzy | PHASE_B6 B6.5 | `_index`, `meta.unmatched_records` | `test_missing_pmid_is_unmatched_never_fuzzy_matched` | pass |
| B6-R06 | PMID-only identity, no DOI/title | PHASE_B6 B6.5 | `_canonical_pmid` | `test_missing_pmid_is_unmatched_never_fuzzy_matched` | pass |
| B6-R07 | Version compatibility enforced | PHASE_B6 B6.6 | `_check_versions` | `test_version_compatibility_matrix` | pass |
| B6-R08 | Membership changes | PHASE_B6 B6.7 | `compare_snapshots` | `test_new_candidate_is_reported_as_added`, neutral-removal | pass |
| B6-R09 | Relevance changes | PHASE_B6 B6.7 | `_compare_records_a` | `test_relevance_change_reports_before_after` | pass |
| B6-R10 | Study design/result changes | PHASE_B6 B6.7 | `_compare_records_a` | `test_study_design_and_result_changes_are_distinct` | pass |
| B6-R11 | Review-state changes | PHASE_B6 B6.7 | `_compare_records_b` | `test_review_requirement_change_reports_sources` | pass |
| B6-R12 | Integrity changes | PHASE_B6 B6.7 | `_compare_records_b` | `test_integrity_change_covers_retraction_and_eligibility` | pass |
| B6-R13 | Extraction changes | PHASE_B6 B6.7 | `_extraction_changes` | added/removed/changed + abstention tests | pass |
| B6-R14 | Ranking changes + membership flag | PHASE_B6 B6.7 | `_compare_records_c` | `test_rank_change_marks_membership_effect_and_placement` | pass |
| B6-R15 | Placement changes | PHASE_B6 B6.7 | `_compare_records_c` | rank/placement test (`became_key_evidence`) | pass |
| B6-R16 | Multiple changes per entity | task 16.11 | per-record aggregation | `test_multiple_changes_on_one_entity_are_all_represented` | pass |
| B6-R17 | Priority versioned + tie-break | PHASE_B6 B6.8 | `CATEGORY_PRIORITY`, sort key | `test_priority_tie_breaking_is_stable` | pass |
| B6-R18 | Audit metadata complete | PHASE_B6 B6.9 | `meta` block | `test_noop_comparison_has_zero_changes_and_valid_artifacts` | pass |
| B6-R19 | Canonical JSON artifact | PHASE_B6 B6.11 | `canonical_json`, `save_comparison` | noop + equivalence tests | pass |
| B6-R20 | Markdown from same result | PHASE_B6 B6.11 | `render_markdown_comparison` | `test_renderers_are_semantically_equivalent` | pass |
| B6-R21 | HTML from same result | PHASE_B6 B6.11 | `render_html_comparison` | equivalence test | pass |
| B6-R22 | No clinical interpretation | PHASE_B6 B6.10 | wording in `_change` descriptions | `test_no_clinical_interpretation_in_descriptions` | pass |
| B6-R23 | Real B5 snapshot compatibility | PHASE_B6 B6.13 | read-only over `b5` dicts | `test_b6_real_b5_snapshots_detect_integrity_and_membership_changes` | pass |
| B6-R24 | B5 regression compatibility | task 18 | no B5 files modified | full suite: 245 passed | pass |
| B6-R25 | Topic scope is explicit; distinct non-empty topics fail closed | PHASE_B6 B6.4a | `_comparability_status` | `test_comparability_different_topics_fail_closed` | pass |
| B6-R26 | Search-query evolution is factual provenance, not a rejection | PHASE_B6 B6.4a | `_comparability_status` | `test_comparability_query_evolution_is_recorded_not_rejected` | pass |
| B6-R27 | Missing/invalid topic produces an explicit scope status | PHASE_B6 B6.4a | `_comparability_status` | unavailable/partial-topic tests | pass |
| B6-R28 | B5 null/absent block transitions remain auditable | PHASE_B6 B6.7 | `_block_availability_changes` | block availability + null/absent + nested-study tests | pass |
| B6-R29 | Review source handoff is detected even if aggregate review stays true | PHASE_B6 B6.7 | `_compare_records_b` | `test_review_source_handoff_is_reported_when_aggregate_stays_true` | pass |
| B6-R30 | Missing-PMID audit records are deterministic and distinguishable | PHASE_B6 B6.5 | `_index`, sorted `unmatched_records` | `test_missing_pmid_audit_records_are_stable_and_distinguishable` | pass |
| B6-R31 | Renderers project canonical comparability metadata | PHASE_B6 B6.11 | renderers | `test_renderers_project_canonical_comparability_metadata` | pass |
| B6-R32 | Semantic comparison ID ignores audit timestamps and candidate-set order while raw IDs retain provenance | PHASE_B6 B6.4/B6.9 | `_semantic_snapshot_id`, `comparison_id` construction | `test_comparison_id_ignores_audit_timestamps_and_article_order` | pass |
| B6-R33 | Full B5-built snapshots serialize, load, compare, and render through the explicit-input CLI | PHASE_B6 B6.3/B6.11/B6.13 | `build_snapshot`, B6 loader/CLI/renderers | `test_real_b5_serialized_cli_comparison_has_expected_artifacts` | pass |
| B6-R34 | Invalid CLI comparison produces no success artifact | PHASE_B6 B6.12 | `main`, `load_snapshot_file` | `test_cli_invalid_inputs_fail_without_success_artifacts` | pass |
| B6-R35 | Repeated identical missing-PMID records retain deterministic audit occurrences | PHASE_B6 B6.5 | unmatched-record occurrence assignment | `test_duplicate_missing_pmid_records_have_deterministic_audit_occurrences` | pass |
| B6-R36 | Stored HTML-like values are escaped in both rendered artifacts | PHASE_B6 B6.11 | Markdown/HTML renderers | `test_markdown_escapes_stored_html_like_values` | pass |
| B6-R37 | Unsupported snapshot-version matrix fails closed | PHASE_B6 B6.6 | `_check_versions` | `test_unsupported_snapshot_versions_fail_closed` | pass |
| B6-R38 | CLI requires both explicit snapshot paths | PHASE_B6 B6.3 | argparse positionals | `test_cli_requires_both_explicit_snapshot_paths` | pass |
