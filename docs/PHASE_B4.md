# Phase B4 policy and extraction

The active profile is `config/report_policy.json`, policy ID
`clinical_research_priority_v1`, version `1.0.0`. It keeps relevance, study
design, abstract-based evidence tier, structured extraction, and report
placement as separate auditable decisions. The product is research support,
not clinical advice, GRADE, formal risk-of-bias assessment, or causal inference.

`app/services/clinical_extraction.py` uses pure, deterministic rules with
structured-abstract priority: METHODS for population and arms, RESULTS for
outcomes and safety, CONCLUSIONS for author-attributed conclusions, followed by
title and unstructured abstract. Every reported field is represented by a
status and supporting provenance span; missing values remain `not_reported`,
`unclear`, or `not_extractable`.

Placement routes principal direct/class-level evidence to Key evidence,
case reports and series to Early safety signals, pharmacovigilance to
Pharmacovigilance signals, narrative reviews and contextual evidence to
Clinical background and overview, and mechanisms/research enablers to
Emerging mechanisms and research trends. Preclinical-only records remain in
audit JSON and are hidden for implicit human clinical queries. Pharmacovigilance
records explicitly retain reporting-bias, no-incidence, and non-causality
limitations.

JSON is the complete source of truth. Markdown and standalone HTML are concise
human views; HTML uses native details blocks and no external assets or runtime.
All extraction is abstract/metadata-based and does not replace full-text review.

## Benchmark boundary

Future EBM-NLP, Evidence Inference, and SYNERGY comparisons may be added through
an offline adapter that accepts a user-provided dataset path. Tests must not
download third-party data, tune on expert test splits, or commit benchmark
datasets. Dataset licenses and attribution must be checked by the user.
