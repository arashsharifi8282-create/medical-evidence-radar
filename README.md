# Medical Evidence Radar

AI-assisted Evidence Discovery for Biomedical Research

## Why Medical Evidence Radar?

[متن جدید]

## Background

[داستان تو]

## Current release: Phase B4.2

[README]

The latest validated automated suite result is **213 passed**.

## Capabilities through Phase B4.2

- **Phase B1 — concept provenance:** retains PubMed MeSH identifiers, resolves
  accepted discovered terms through exact-first RxNorm lookup, preserves
  unresolved terms, and emits only `ARTICLE_MENTIONS_CONCEPT`. It does not infer
  treatment, efficacy, safety, causality, or association relationships.
- **Phase B2 — clinical relevance:** builds an explicit intervention/condition
  target and classifies every candidate as `direct`, `class_level`,
  `contextual`, or `irrelevant` using field-aware source signals. Approved
  class-level evidence requires a structural `has_member`, `isa`, or `part_of`
  relationship from ATC or MEDRT.
- **Phase B2.2 — intent and focus:** adds query-intent, article-focus,
  condition-coherence, population-scope, content-role, and needs-review rules.
  Co-occurrence alone is not enough for direct relevance. Frozen reviewer data
  is retained for regression/replay, not treated as official gold-standard
  adjudication.
- **Phase B3 — study assessment:** separates relevance from study design and
  abstract-based evidence strength. It records design family, result status,
  population scope, sample size, comparator, follow-up, limitations, supporting
  spans, named rules, and conservative triage tiers.
- **Phase B4 — clinical extraction and policy:** extracts source-supported
  population, intervention/regimen, comparator, duration/follow-up, outcomes,
  effects, and safety fields. The versioned report policy routes evidence into
  explicit report sections while preserving the complete JSON audit.
- **Phase B4.1 — real-record presentation validation:** replays 20 normalized
  Acyclovir and Losartan PubMed records and verifies consistent clinical cards
  and centralized report placement across JSON, Markdown, and HTML.
- **Phase B4.2 — role-aware multi-topic validation:** distinguishes a requested
  intervention used as the primary intervention from background,
  pharmacokinetic-reference, rescue/concomitant, and other non-primary roles.
  A deterministic 24-record Acyclovir/Losartan evaluator validates development
  and holdout splits, conservative extraction, provenance, ranking, placement,
  and renderer integrity. An additional fixed 8-record replay covers bounded
  defects found during final live validation.

## Current pipeline

1. **Retrieve** — send the original free-text topic to PubMed ESearch, sorted by
   publication date, then EFetch normalized article metadata and abstracts.
2. **Normalize and de-duplicate** — preserve PMID, DOI, URL, publication types,
   dates, structured abstract sections, MeSH descriptors, and author keywords.
3. **Assess relevance** — construct the clinical target and evaluate intent,
   focus, intervention role, condition support, population scope, and explicit
   field-level signals for every candidate.
4. **Assess the study** — classify design and result status, then record
   abstract-based evidence-strength signals and limitations without conflating
   them with relevance.
5. **Extract clinical fields** — conservatively extract only supported values,
   each with status, source section/span, rule ID, and rule version; otherwise
   abstain explicitly.
6. **Rank** — apply named, reconstructable lexicographic ranking components.
7. **Place** — use `config/report_policy.json` to route principal evidence,
   safety signals, pharmacovigilance, background, emerging mechanisms, and
   audit-only records without losing selected articles.
8. **Report** — persist complete JSON audit data plus concise Markdown and
   standalone HTML views. Topic profiles and concept artifacts are optional
   local outputs.

## Validation status

Phase B4.2 has controlled multi-topic validation for:

- **Acyclovir efficacy and safety in herpes zoster**
- **Losartan efficacy and safety in hypertension**

The checksummed benchmark contains 24 records: 12 development and 12 holdout,
with both topics represented in each split. Its acceptance gates pass by split,
by topic, and overall. Accepted extraction values have 1.0 precision in the
current evaluator; malformed values, unsupported effect/safety outputs, and
provenance failures are zero. Ranking reconstruction, placement uniqueness,
selected-article retention, renderer agreement, protocol/result separation,
and key-evidence relevance checks also report zero failures. Coverage is
intentionally lower where abstracts do not safely report a field.

Automated tests are offline and use controlled fixtures, fake transports, and
temporary directories. Live CLI runs use PubMed and RxNorm network services.

## Limitations and safety boundary

- **Abstract/metadata only:** assessment and extraction do not inspect article
  full text.
- **Conservative abstention:** missing or ambiguous values remain
  `not_reported`, `unclear`, `not_extractable`, or another explicit abstention;
  lower extraction coverage is preferred to unsupported output.
- **No LLM:** all current decisions are deterministic rules; no opaque model or
  generated PubMed query is used.
- **No full-text scraping:** the tool uses PubMed EUtils metadata and abstracts
  only.
- **No clinical inference beyond the text:** it does not infer diagnosis,
  treatment recommendations, causality, regulatory approval, or unreported
  clinical relationships.
- The study tier is not GRADE, certainty-of-evidence grading, or formal
  risk-of-bias assessment. Reports require source review before research use.
- PubMed is the only literature source in the current release. Live RxNorm may
  resolve an intervention while returning no approved structural RxClass parent;
  the engine does not guess class-level evidence in that case.

## Installation

Python 3.10 or newer is recommended. On Windows PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Run the tests

Canonical validation command:

```powershell
.\.venv\Scripts\python.exe -m pytest -ra -W default
```

## Run the CLI

Print the default topic's ranked results without writing artifacts:

```powershell
.\.venv\Scripts\python.exe -m app.sources.pubmed.cli
```

Run the validated Losartan topic with an explicit target and save JSON,
Markdown, HTML, topic-profile, and concept outputs:

```powershell
.\.venv\Scripts\python.exe -m app.sources.pubmed.cli `
  --topic "losartan efficacy and safety in hypertension" `
  --intervention losartan `
  --condition hypertension `
  --candidate-limit 50 `
  --report-limit 10 `
  --save
```

Equivalent Acyclovir example:

```powershell
.\.venv\Scripts\python.exe -m app.sources.pubmed.cli `
  --topic "acyclovir efficacy and safety in herpes zoster" `
  --intervention acyclovir `
  --condition "herpes zoster" `
  --candidate-limit 50 `
  --report-limit 10 `
  --save
```

With `--save`, runtime artifacts are written under `data/raw/pubmed/`,
`data/topic_profiles/`, `data/concepts/`, and `reports/pubmed/`. They are local
audit outputs and must not be committed by default. The HTML report is
self-contained and uses no JavaScript, CDN, server, or frontend framework.

## Key architecture

```text
app/sources/pubmed/       PubMed client and CLI orchestration
app/sources/rxnorm/       RxNorm lookup and approved RxClass provenance
app/models/               Article, relevance, study, clinical, and audit models
app/services/normalizer.py
app/services/relevance.py
app/services/study_design.py
app/services/clinical_extraction.py
app/services/report_policy.py
app/services/persistence.py
config/report_policy.json Versioned deterministic placement policy
tests/                    Offline unit, replay, benchmark, and integrity coverage
```

## Phase documentation

- [Phase B4 policy and extraction](docs/PHASE_B4.md)
- [Phase B4.1 real extraction validation and presentation](docs/PHASE_B4_1.md)
- [Phase B4.2 multi-topic validation release](docs/PHASE_B4_2.md)

## Service limits

The PubMed client defaults to a 0.34-second delay between outbound requests to
respect the NCBI EUtils guideline of no more than three requests per second
without an API key. RxNorm responses are cached locally to avoid repeated
lookups.
