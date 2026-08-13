# Phase B4.1 — Real extraction validation and report presentation

B4.1 adds an offline replay fixture containing 20 normalized PubMed records (10
acyclovir and 10 losartan), with PMID/DOI/URL provenance preserved. Extraction
is section- and sentence-aware for population, dose, comparator, duration, and
follow-up fields; values remain unknown when the abstract does not support a
claim.

Report placement is applied centrally from `config/report_policy.json`. Principal
evidence is capped by the configured limit, while safety, pharmacovigilance,
contextual, trend, and audit routing remains explicit. Markdown and standalone
HTML render the same clinical evidence card fields: population, intervention,
comparator, outcomes, effects, safety, limitations, and supporting spans.

The abstract and technical audit are collapsed by default in HTML/Markdown.
This phase remains abstract/metadata-based research support and is not GRADE,
formal risk-of-bias assessment, or clinical advice.
