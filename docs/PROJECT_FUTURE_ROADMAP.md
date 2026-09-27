# Medical Evidence Radar — Project Future Roadmap

## Verification record

- Repository: `C:\projects\medical-evidence-radar`
- Last repository verification: 2026-08-27 (Asia/Tehran)
- HEAD verified: `08c068694488b5bbfd8d7e82a97f05e14e5859db`
- B4.2 baseline verified: `1330491138dc9b6534f5d039bee1d997ed9213ae`
- B4.2 tag verified: `v0.4.2` points to `1330491138dc9b6534f5d039bee1d997ed9213ae`
- B5 release verified: `v0.5.0` points to `08c068694488b5bbfd8d7e82a97f05e14e5859db`
- Verification basis: Git history and tags, tracked production code, tracked tests and fixtures, `README.md`, `docs/PHASE_B4_2.md`, and `docs/PHASE_B5.md`
- Verification scope: documentation-only inspection. The test results cited below are release results recorded in tracked documentation; this roadmap task did not rerun the suites.
- 2026-09-26 re-verification: HEAD `2640a76080e7b393aa5a67824cd312fc74f5c925` = tag `v0.6.0`; canonical suite 269 passed (44 B6), per B7 research checkpoint; B6 production, fixtures, tests, `docs/PHASE_B6.md` and `docs/PHASE_B6_RTM.md` present. The earlier 2026-08-27 record remains historical.

## 1. Document purpose

This file is the durable project-direction and handoff reference for future maintainers and coding agents. It must be read at the start of every roadmap or implementation task, together with `AGENTS.md` and the specification for the phase being considered.

This roadmap is self-contained, but it is not a substitute for inspecting Git, production code, tests, controlled fixtures, configuration, and phase documentation. Repository evidence is the source of truth when this file becomes stale or conflicts with the checked-out repository.

This roadmap does not grant automatic permission to implement a phase, edit unrelated files, stage changes, commit, tag, push, open a pull request, or perform any other remote action. Every implementation phase requires an independent, explicit specification and authorization.

## 2. Project identity

Medical Evidence Radar is a deterministic, source-linked research-support tool. It retrieves recent PubMed evidence, normalizes retained metadata and abstracts, classifies clinical relevance, assesses study characteristics, extracts source-supported clinical fields, ranks candidates through named rules, and persists auditable JSON plus concise Markdown and HTML reports.

The project is not clinical decision support, a medical-advice system, a clinical recommendation engine, or an LLM evidence engine. It must not diagnose, recommend treatment, imply regulatory approval, manufacture clinical certainty, or draw conclusions beyond retained source evidence. Relevance, publication integrity, evidence quality, extraction, ranking, and report placement are separate auditable decisions.

The current evidence boundary is PubMed abstracts and structured metadata. RxNorm and approved structural RxClass provenance support concept resolution and bounded class-level relevance. The system does not currently inspect full text, publisher pages, Crossref, Retraction Watch, regulatory sources, guidelines, or citation graphs.

## 3. Current verified state

| Phase | Status | Commit/Tag | Verified capabilities | Remaining limitations |
|---|---|---|---|---|
| B4.2 — Role-aware multi-topic validation | `VERIFIED_COMPLETE` | Baseline `1330491138dc9b6534f5d039bee1d997ed9213ae`; tag `v0.4.2`. Main implementation/fix commits are recorded in `docs/PHASE_B4_2.md`. | Deterministic 24-record development/holdout benchmark across Acyclovir and Losartan topics; fixed eight-record live-regression replay; role-aware relevance; conservative extraction; ranking reconstruction; placement uniqueness; provenance; JSON/Markdown/HTML agreement and escaping checks. | Abstract/metadata only; two-topic controlled regression is not universal validation; extraction intentionally abstains when support is inadequate; class-level evidence still requires an approved ATC/MEDRT structural relation. |
| B5 — Publication Integrity & Retraction Safety | `VERIFIED_COMPLETE` | `08c068694488b5bbfd8d7e82a97f05e14e5859db` (`Add publication integrity safeguards`); tag `v0.5.0`. | Typed integrity assessment; retained and normalized PubMed `CommentsCorrections`; independent versioned rule `PUBMED_PUBLICATION_INTEGRITY` `1.0`; deterministic taxonomy and precedence; conservative eligibility filtering before ranking; checksummed nine-record fixture; offline tests; complete JSON audit and concise, escaped Markdown/HTML warnings with placement agreement. | PubMed structured metadata only; `no_signal` is not proof of validity; no publisher, Crossref, Retraction Watch, full-text, citation-network, guideline, or regulatory verification; correction severity and clinical significance are not inferred. |
| B6 — Longitudinal Evidence Change Detection | `VERIFIED_COMPLETE` | `2640a76080e7b393aa5a67824cd312fc74f5c925`, tag `v0.6.0`. | B6 compares explicit `b5` snapshots by PMID; production, fixtures, tests, specification and RTM present. | No regulatory snapshot comparisons, implicit baseline or scheduler. |

**Phase B6 is complete and released as v0.6.0. B7 FDA-only MVP scope is
approved and its implementation is present locally, but B7 is uncommitted,
unreleased, and pending second independent acceptance review. No `v0.7.0` is
published or implied.**

### Verification evidence and conflicts

- Git verifies that `v0.4.2` still points exactly to the B4.2 baseline and that HEAD is the B5 commit tagged `v0.5.0`.
- B5 production evidence is present in `app/models/integrity.py`, `app/models/article.py`, `app/services/integrity.py`, `app/services/normalizer.py`, `app/services/relevance.py`, `app/services/persistence.py`, and `app/sources/pubmed/cli.py`.
- B5 test and fixture evidence is present in `tests/test_b5_integrity.py` and `tests/fixtures/b5_publication_integrity/`. `docs/PHASE_B5.md` records two deterministic focused runs with 12 passing tests and a canonical result of 225 passing tests.
- No tracked B6 file, comparison CLI option, comparison policy, comparison schema, B6 fixture, or B6 test was found at the verified HEAD.
- `CONFLICT`: `AGENTS.md` line 18 says the completed local checkpoint is Phase B2.2B.2. That checkpoint statement is stale relative to Git HEAD, tag `v0.5.0`, `README.md`, the B5 production/test files, and `docs/PHASE_B5.md`. The safety, provenance, scope, and repository-hygiene instructions in `AGENTS.md` remain binding; only its checkpoint statement is superseded by verified repository evidence.
- No phase status in the table is `UNVERIFIED`. Historical test counts are verified as tracked release documentation, but were not independently rerun during this roadmap-only task.

## 4. Non-negotiable engineering principles

- Behavior must remain deterministic.
- Decisions must be explainable through named rules.
- Provenance must be preserved end to end.
- Outputs must remain linked to their retained sources.
- Ambiguous or unsupported values require conservative abstention.
- Automated acceptance tests must be offline and deterministic.
- External clients must be injectable so tests do not require live services.
- Production logic must not contain topic-, drug-, disease-, PMID-, or fixture-specific branches.
- Fixture identifiers, fixture names, and expected fixture values must not appear in production rules.
- Backward compatibility is required unless a contract is explicitly and deliberately versioned.
- CLI evolution must be additive; legacy invocation behavior must remain unchanged unless separately approved.
- Existing user dirty state must be inspected and preserved.
- Schema and policy contract changes must never be silent; identifiers, versions, compatibility behavior, and migration consequences must be explicit.
- JSON, Markdown, and HTML must agree semantically about selected records, placement, warnings, and changes.
- All HTML-controlled and source-derived text must be escaped.
- Code, tests, reports, and console behavior must remain compatible with Windows and cp1252-constrained environments; avoid output that depends on unsupported console characters.
- Generated reports and runtime data under `data/` and `reports/` must not accidentally enter commits.
- When staging is explicitly authorized, stage exact paths only.
- Never use `git add .`, `git add -A`, or wildcard staging.
- Do not push, tag, open a pull request, or perform any other remote action unless explicitly requested.
- Keep relevance separate from evidence quality and publication integrity. A B2 relevance result must not be silently rewritten by B5 or B6.
- Do not infer a relationship, validity judgment, clinical effect, or reason for absence from co-occurrence or missing data.

## 5. Phase B6 — next approved work

### Title and objective

**Longitudinal Evidence Change Detection**

B6 is to compare two compatible saved snapshots through a read-only, deterministic workflow. The baseline must be supplied explicitly. The likely CLI shape is additive, such as `--compare-to`, but the exact option name remains an open decision until the B6 specification fixes it.

B6 must identify structured changes in available evidence without clinical interpretation. It must not modify the baseline, auto-discover a “latest” baseline, reinterpret absence as invalidation, or change legacy behavior when comparison is not requested.

### Baseline contract

- Accept only an explicitly supplied baseline snapshot.
- Validate that the baseline exists, is readable, is structurally valid, and is version-compatible with the current snapshot.
- Produce a clear, actionable error for a missing, malformed, unsupported, or incompatible baseline.
- Keep the baseline byte-for-byte unchanged.
- Treat compatible older snapshots conservatively: newly introduced optional fields must not make an otherwise compatible snapshot fail without a documented compatibility reason.
- Do not select a baseline automatically by timestamp, filename, directory order, report history, or any other heuristic.
- Without the comparison option, preserve the existing B5 retrieval, assessment, ranking, persistence, rendering, and CLI behavior.

### Article identity

- PMID is the primary article identity.
- Fuzzy title matching is prohibited.
- Duplicate PMIDs must be rejected or resolved by one documented deterministic rule; the B6 specification must choose and test the behavior.
- Missing PMIDs require explicit, tested behavior. They must not be silently matched by title, DOI similarity, order, or co-occurrence.

### Membership taxonomy

B6 must represent at least these mutually understandable membership outcomes:

- `retained`
- `new_in_current_candidate_set`
- `not_in_current_candidate_set`

`not_in_current_candidate_set` means only that a baseline PMID is absent from the current candidate set. It must not be described as retracted, deleted, disproven, invalid, or no longer evidence. Retrieval windows, query results, service availability, and candidate limits can change membership without changing publication validity.

### Field-level change taxonomy

B6 must detect and describe at least:

- relevance transition;
- study status or protocol/result transition;
- study-design change;
- `needs_review` change;
- publication-integrity transition;
- integrity-eligibility change;
- correction or update addition;
- accepted extraction value change;
- accepted-to-abstention transition;
- abstention-to-accepted transition;
- provenance-only change;
- rank change;
- placement change;
- new Key Evidence; and
- comparability warning.

Whitespace, key order, formatting, serialization differences, or other representation-only changes must not produce a semantic change. Normalization must be narrow, explicit, and tested so it cannot erase meaningful source or provenance differences.

### Priority policy

Change priority must be determined by an explicit, named, independently versioned comparison policy. Integrity escalation, loss of integrity eligibility, and material extraction transitions must rank above rank-only, placement-only, or provenance-only changes. The policy must not imply clinical importance, treatment impact, or certainty. Every priority assignment must be reconstructable from the recorded change facts and policy version.

### Persistence and rendering

- Persist the complete comparison audit in JSON.
- Render concise, semantically equivalent Markdown and standalone HTML views.
- Preserve identical membership, change categories, priorities, warnings, and article identity across all three formats.
- Prevent duplicate placement, duplicate article representation, disappearance of selected records, and renderer disagreement.
- Escape all source-derived and user-controlled HTML content.
- Record baseline identity, current snapshot identity, relevant schema versions, comparison-policy version, and compatibility warnings.
- Never overwrite either input snapshot as a side effect of comparison.

### B6 exclusions

The B6 implementation must not add:

- a scheduler or monthly automation;
- email or notification delivery;
- a database, history database, or automatic archive/deletion workflow;
- a hosted dashboard or user interface;
- guideline or regulatory ingestion;
- FDA, EMA, WHO, NICE, or other B7 source ingestion;
- Crossref or Retraction Watch integration;
- full-text acquisition or analysis;
- a citation graph;
- LLM summarization;
- clinical recommendations or clinical interpretation;
- statistical meta-analysis;
- automatic latest-baseline selection;
- fuzzy article matching;
- multilingual report generation; or
- any B7 functionality.

## 6. Proposed future phases

Except for the approved, local, uncommitted B7 FDA-only MVP described below,
the phases below are `PROPOSED`, not approved implementation commitments.

| Phase | Status | Proposed direction | Why it follows | Dependencies | Primary safety boundary | Still undecided |
|---|---|---|---|---|---|---|
| B7 | `APPROVED_SCOPE_LOCAL_IMPLEMENTATION_PENDING_ACCEPTANCE` | FDA Drugs@FDA application metadata only; US, metadata-only, no PDFs, no B6 extension or pairwise B7 comparison | Approved authority-specific provenance, licensing, schema, normalization, and retention contracts are implemented locally; one controlled keyed D6 attestation is recorded. | Completed B6; second independent acceptance review; separately authorized staging/release work. | Never represent record presence as approval, recommendation, equivalence, applicability, or a complete dossier; no other authority is activated. | Future source drift, release acceptance, and any EMA/WHO/NICE scope remain separate. |
| B8 | `PROPOSED` | Temporal monitoring and repeat-run orchestration | Repeat execution should follow deterministic, source-aware change detection rather than inventing change semantics in an orchestrator. | Completed B6; likely B7 source contracts if external sources are monitored; immutable run metadata and failure handling. | Automation must not mutate historical evidence or hide partial/failed retrieval. | Execution platform, cadence, retries, retention, locking, reproducibility, and operator controls. |
| B9 | `PROPOSED` | Strictly cited LLM-assisted summaries over verified structured evidence | Any generative layer must consume already normalized, provenance-rich, comparison-aware evidence rather than control classification or ranking. | Stable schemas through B6/B8; citation binding; evaluation corpus; prompt/model/version audit; abstention rules. | LLM output cannot alter deterministic classification, ranking, integrity eligibility, or source facts, and every claim must be traceable to verified structured evidence. | Model/provider, privacy boundary, evaluation thresholds, prompt/version lifecycle, citation granularity, and human-review workflow. |
| B10 | `PROPOSED` | Scheduling and notification/email workflows | Notifications should follow stable orchestration and validated summaries so delivery does not define evidence semantics. | Completed B8; B9 only if generated summaries are included; identity, security, privacy, consent, secrets, and delivery audit. | Never send unsupported clinical claims, sensitive runtime data, secrets, or ambiguous partial-run results. | Channels, recipients, consent, throttling, escalation, failure recovery, content templates, and data retention. |
| B11 | `PROPOSED` | User interface and operational dashboard | A UI should present stable source, comparison, orchestration, and notification contracts rather than becoming their undocumented implementation. | Stable APIs/schemas from earlier approved phases; accessibility, authentication, authorization, security, and deployment decisions. | Preserve provenance, uncertainty, warnings, and separation of relevance, quality, integrity, and change; do not imply clinical decision support. | UI architecture, hosting, auth model, tenancy, accessibility target, operational ownership, and threat model. |

The numbering, scope, and ordering of B7 through B11 may change after a future
repository audit. B7 has the limited approved/local state recorded above; B8+
may not be implemented without a separate specification, explicit approval,
requirement matrix, acceptance gates, and compatibility plan.

## 7. Explicit non-goals

- Medical diagnosis.
- Treatment recommendation or prescribing guidance.
- Replacement of clinicians, systematic reviews, formal evidence synthesis, GRADE, or formal risk-of-bias assessment.
- Fabrication of certainty, missing values, citations, identifiers, relationships, or evidence claims.
- Interpreting absence from a snapshot, candidate set, abstract, or metadata field as proof that no evidence or event exists.
- Hiding, weakening, or discarding provenance and uncertainty.
- Allowing an LLM to change deterministic classification, ranking, extraction, integrity eligibility, or comparison results without a separately approved contract.
- Production rules specialized for a PMID, fixture, drug, disease, topic, benchmark, or expected test value.
- Automatic mutation, deletion, or rewriting of historical snapshots and reports.
- Clinical interpretation of publication-integrity signals, corrections, retractions, or longitudinal changes.

## 8. Agent startup protocol

Before starting any future phase or roadmap task, the agent must:

1. Confirm the exact repository root and avoid similarly named repositories.
2. Read `AGENTS.md` and this roadmap in full.
3. Inspect HEAD, tags, status, index, unstaged diff, untracked files, and existing user dirty state.
4. Verify the current phase from Git, production code, tests, fixtures, configuration, and tracked documentation.
5. Locate and read the standalone specification for the requested phase. Stop if implementation is requested but no adequate specification or authority exists.
6. Build a requirement matrix linking each requirement to production code, tests, fixtures, persistence, renderers, compatibility, and exclusions.
7. Write general, offline failing tests first; do not encode fixture identifiers or expected values into production logic.
8. Run focused tests deterministically twice, then all required compatibility suites and the canonical suite.
9. Validate controlled-file parsing, manifest membership, and required checksums.
10. Perform an anti-overfitting scan for fixture names, PMIDs, topic strings, expected values, and special-case branches in production code.
11. If staging is explicitly authorized, stage only exact related paths and inspect the staged diff.
12. Do not commit or perform any remote action without explicit permission.

**This roadmap explains direction; it does not authorize implementation.**

## 9. Definition of phase completion

A phase may be declared complete only when all applicable gates are satisfied and evidenced:

- the production implementation exists;
- the focused suite passes twice with deterministic results;
- required compatibility suites pass;
- the canonical suite passes;
- controlled fixture membership and required checksums are valid;
- documentation is current and consistent with behavior;
- all controlled JSON, JSONL, XML, configuration, or other required files parse successfully;
- the anti-overfitting scan passes;
- pre-existing user dirty state is preserved;
- the expected commit exists in Git when the phase specification requires a commit; and
- a precise, evidence-backed final report records commands, results, limitations, and any remaining conflict.

An audit, plan, document review, partial implementation, passing subset of tests, or uncommitted working-tree content is not phase completion by itself.

## 10. Roadmap maintenance protocol

- Update this roadmap only after verified phase completion or an explicit roadmap decision.
- Attach every implemented-state claim to a commit hash, tag, or tracked evidence path.
- Keep implemented facts, approved-next work, proposals, and open questions in separate sections and use explicit statuses.
- Do not erase obsolete decisions. Move them to **Superseded decisions** with the replacement evidence and verification date.
- Record the last verification date, repository root, and exact HEAD checked.
- When the repository and roadmap disagree, the repository is authoritative; record and correct the conflict rather than rationalizing it away.
- Never declare phase completion solely because this roadmap says a phase is complete. Re-run the startup protocol and inspect current evidence.
- Preserve compatibility and migration notes whenever a schema, policy, CLI, fixture, or persistence contract changes.

### Superseded decisions

- 2026-09-26: prior B6 `APPROVED_NEXT` and no-implementation assertions in the phase table/status statement are superseded by `2640a76` and `v0.6.0`; historical August 2026 verification remains accurate for its original date. Historical B6 planning and decision-log rows below remain intact.
- 2026-09-26: B7 rows describing all decisions as pending, no implementation,
  or a never-executed D6 are superseded by approved FDA-only scope, local
  implementation evidence, and the durable controlled D6 attestation. The
  first independent review was rejected/blocked; this does not mark B7 accepted
  or released.
- The `AGENTS.md` checkpoint statement “Completed local checkpoint: Phase B2.2B.2” is superseded for status reporting by verified B4.2 and B5 Git evidence at HEAD `08c068694488b5bbfd8d7e82a97f05e14e5859db`. Its engineering and safety instructions are not superseded.

## 11. Decision log

| Date | Decision | Status | Evidence | Consequence |
|---|---|---|---|---|
| 2026-08-27 verification date | Preserve B4.2 as the official baseline. | `VERIFIED_COMPLETE` | `v0.4.2` resolves to `1330491138dc9b6534f5d039bee1d997ed9213ae`; `docs/PHASE_B4_2.md`. | Future compatibility and B6 planning must not rewrite or relabel the baseline. |
| 2026-08-27 commit date | B5 is the publication-integrity and retraction-safety phase. | `VERIFIED_COMPLETE` | Commit `08c068694488b5bbfd8d7e82a97f05e14e5859db`, tag `v0.5.0`, `docs/PHASE_B5.md`, B5 production/test paths. | Integrity remains independent of relevance and filters eligibility before ordinary evidence ranking. |
| 2026-09-26 | B6 complete/released v0.6.0; B7 FDA-only metadata scope approved, schema conditional, implementation complete, and controlled keyed D6 attestation recorded and independently accepted. | B6 `VERIFIED_COMPLETE`; B7 `ACCEPTED_RELEASE_PREPARATION` | `2640a76`, `v0.6.0`, B7 source/tests/docs, M0 source contract, D6 attestation contract, second independent acceptance | B8+ remain separate; no other authority is activated; first independent review remains historically rejected/blocked. |
| Date not verified | B6 comparisons require an explicit baseline. | `APPROVED_NEXT` | Approved roadmap contract; compatible with the future boundary in `docs/PHASE_B5.md`. | No implicit or automatic baseline selection is allowed. |
| Date not verified | Fuzzy identity matching is prohibited in B6. | `APPROVED_NEXT` | Approved roadmap contract. | PMID remains primary identity; missing or duplicate PMID behavior must be explicit and tested. |
| Date not verified | Baseline auto-discovery is prohibited in B6. | `APPROVED_NEXT` | Approved roadmap contract. | CLI comparison must remain opt-in and deterministic. |
| Date not verified | B7 is separate from B6. | `PROPOSED` | B6 exclusions and proposed-future-phase ordering in this roadmap. | B6 cannot ingest regulatory or guideline sources. |
| Date not verified | Clinical recommendation is outside project scope. | `VERIFIED_COMPLETE` | `AGENTS.md`, `README.md`, `docs/PHASE_B4_2.md`, and `docs/PHASE_B5.md`. | No phase may turn evidence retrieval or change detection into treatment advice. |

## 12. Open questions

These questions are intentionally unresolved. A future phase specification must answer the applicable items; agents must not invent answers.

- What is the final B6 comparison snapshot schema, including schema identifier, compatibility matrix, and baseline/current metadata?
- Is the final additive CLI option exactly `--compare-to`, or another explicitly documented name?
- Should duplicate PMIDs be rejected, deterministically collapsed, or represented as a comparability error?
- What is the explicit B6 behavior for records without a PMID?
- What fields constitute a material extraction change, and how are equivalent normalized values defined without hiding provenance differences?
- What is the policy-version migration strategy for integrity, ranking, placement, extraction, and future comparison policies?
- Which official sources, document types, jurisdictions, and update mechanisms are in the exact B7 scope?
- How will B8 orchestration handle cadence, retries, concurrency, partial failures, immutable run identity, and retention?
- What security, privacy, consent, secret-management, and abuse-prevention requirements must be satisfied before scheduling or email is considered?
- What model, evaluation, citation-binding, privacy, and human-review contracts would be required before any B9 LLM assistance?
- What UI architecture, deployment boundary, authentication model, accessibility target, and operational ownership would apply to B11?
