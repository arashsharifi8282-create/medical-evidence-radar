# Phase B4.2 — Role-aware multi-topic validation release

## Goal and scope

Phase B4.2 closes the validation and release-hygiene gap around the existing B4
abstract/metadata pipeline. It validates that relevance, study assessment,
clinical extraction, ranking, report placement, and JSON/Markdown/HTML
presentation remain deterministic, source-grounded, and internally consistent
across more than one clinical topic.

The controlled topics are:

- Acyclovir efficacy and safety in herpes zoster
- Losartan efficacy and safety in hypertension

This phase does not add an LLM, full-text acquisition or scraping, clinical
recommendations, causal inference, GRADE, formal risk-of-bias assessment, a
database, or a web application. It remains research support rather than
clinical decision support.

## Role-aware relevance

B4.2 strengthens the distinction between mention and requested-intervention
focus. A candidate can mention the requested drug while using it as a
pharmacokinetic reference, background standard, rescue/concomitant therapy, or
another non-primary role. Such co-occurrence is not sufficient for `direct`
relevance.

The relevance audit records the requested intervention role, condition support,
decision, and a source-grounded supporting span. Direct evidence requires the
requested intervention in an appropriate primary/focused role together with
coherent target-condition and query-intent support. The existing conservative
class-level boundary remains unchanged: only approved structural RxClass
relationships from ATC or MEDRT qualify.

## Deterministic multi-topic evaluator

`tests/b4_2_evaluator.py` is an offline evaluator over the checksummed fixture
in `tests/fixtures/b4_2_multi_topic/`. It reconstructs predictions through the
production relevance, study-design, clinical-extraction, ranking, placement,
and persistence paths; it does not contain topic- or PMID-specific production
rules.

For every record it evaluates:

- relevance class, requested intervention role, condition support, and B2
  inclusion decision;
- study design family, result/completion status, needs-review state, and false
  conflict signals;
- population, intervention, comparator, sample size, treatment duration,
  follow-up, outcome, effect, and safety fields;
- provenance membership in the retained title/abstract/structured sections;
- malformed or incomplete values and unsupported accepted values; and
- end-to-end ranking, selection, placement, JSON representation, Markdown/HTML
  agreement, and HTML escaping invariants.

Normalization in the evaluator is limited to transparent Unicode, case,
whitespace, and punctuation normalization. Production code is checked to ensure
that benchmark PMIDs, fixture names, and topic strings are not embedded.

## Development and holdout benchmark

The benchmark manifest defines 24 unique records and fixes checksums for the
record registry, normalized source records, and expected labels:

- 12 development records;
- 12 holdout records;
- 12 Acyclovir/herpes-zoster records;
- 12 Losartan/hypertension records; and
- both topics represented in both splits.

All relevance, study, and extraction fields remain in their scoring
denominators. The benchmark's explicit ambiguity policy prefers `not_reported`
or `not_extractable` over unsupported output. Free-text summaries and inferred
clinical significance are excluded from scoring.

The labels are controlled regression expectations for this release. As with
other pilot reviewer material in the repository, they should not be presented
as external official gold-standard adjudication.

## Conservative field extraction and provenance

Extraction remains section- and sentence-aware, with structured abstract
sections preferred when available. Accepted values must have a status, exact
supporting span, source section/field, rule ID, and rule version. The source
abstract is not rewritten.

When an abstract does not safely support a field, B4.2 abstains. This is why
precision and provenance gates are primary acceptance criteria and coverage can
be intentionally low, especially for follow-up, effects, or treatment duration.
The phase specifically protects against partial comparators, malformed numeric
fragments, arm counts mistaken for total sample size, protocol methods presented
as completed results, and safety/effect text inferred from non-result contexts.

## Ranking and placement invariants

The evaluator and replay tests enforce the following invariants:

- named ranking components reproduce the production ordering;
- each selected PMID appears once and is represented in the JSON audit;
- selected articles do not disappear during placement;
- primary, collapsed, visible, and audit-only sets do not overlap incorrectly;
- irrelevant records do not enter key evidence;
- protocol records are not represented as reported completed results;
- Markdown and HTML contain the same expected linked selected PMIDs; and
- HTML titles remain escaped.

JSON remains the complete audit source of truth. Markdown and standalone HTML
are concise human views governed by `config/report_policy.json` and do not
replace the source record.

## Live regression corrections

The final bounded live smoke for Acyclovir and Losartan exposed a small set of
generic defects involving incomplete population/comparator spans, sample-size
selection, requested-drug role, and study-design interpretation. Commit
`8e50d91fd64f8b2ae8924556869795fcb58d470b` corrected those generic rules and
added `tests/fixtures/b4_2_live_regressions_v1/`.

That fixed replay contains eight read-only records copied from retained live
PubMed snapshots, four per topic. Only the named affected field or relevance
label is adjudicated. Its manifest checksum and ordered PMID membership are
tested, close positive and negative examples protect against overcorrection,
and production modules are checked for embedded fixture identifiers.

The retained live snapshots and generated reports are local audit outputs; they
are not release artifacts and are not committed.

## Acceptance gates and final results

The release gates are:

- the canonical full offline suite;
- focused B4.2 benchmark and live-regression tests;
- frozen B2.2B replay;
- parsing of all controlled tracked JSON and JSONL files;
- benchmark checksum, membership, split, and source-grounding checks;
- zero malformed accepted values;
- zero unsupported effect and safety outputs;
- zero provenance failures;
- 1.0 sample-size, follow-up, and effect precision;
- at least 0.95 comparator, population, intervention, role, and study-design
  performance where applicable;
- zero ranking/placement/renderer integrity failures; and
- repository diff, README link/command, staging, and generated-output hygiene.

Final Phase B4.2 evaluator results:

- all development, holdout, per-topic, and overall threshold sets pass;
- relevance class, role, condition, inclusion, and direct precision are 1.0;
- study-design and result-status accuracy are 1.0, with zero false conflicts;
- all accepted extraction fields have 1.0 precision in the evaluator;
- malformed values, unsupported effect/safety outputs, and provenance failures
  are zero;
- all ranking, placement, renderer, protocol, relevance, and escaping integrity
  failure counts are zero; and
- the latest validated repository suite result is **213 passed**.

Coverage is not claimed as 1.0: conservative abstention deliberately leaves
fields empty when the abstract lacks safe support.

## Main B4.2 commits

- `2b0bb5538f44df02589e65aa7e129a9d5fdb8e91` — Add multi-topic clinical
  extraction validation: role-aware relevance support, the checksummed
  24-record Acyclovir/Losartan benchmark, deterministic evaluator, and
  integrity tests.
- `8e50d91fd64f8b2ae8924556869795fcb58d470b` — Fix live multi-topic validation
  regressions: generic extraction/relevance/study fixes plus the fixed
  eight-record live regression replay.

## Remaining limitations and next-phase boundary

- Evidence remains limited to PubMed abstracts and metadata; full-text claims,
  tables, appendices, and supplementary material are not evaluated.
- Extraction is intentionally conservative and incomplete. Absence from an
  abstract is not evidence that a clinical characteristic or event was absent.
- The two-topic benchmark demonstrates controlled regression behavior, not
  universal clinical-domain generalization or external validation.
- Relevance and evidence-strength rules are deterministic heuristics, not
  clinical judgment, treatment guidance, regulatory review, GRADE, or formal
  risk-of-bias assessment.
- No clinical relationship or significance may be inferred beyond explicit
  source text. Co-occurrence alone remains insufficient.
- RxClass evidence remains unavailable when the live builder has no approved
  structural ATC/MEDRT relationship; no fallback authority is invented.

Any next phase that adds more topics, external benchmarks, full text, new
terminology authorities, statistical synthesis, LLM assistance, or clinical
interpretation requires separate scope approval, provenance/schema decisions,
and new acceptance criteria. B4.2 itself closes only the deterministic
multi-topic abstract/metadata validation release.