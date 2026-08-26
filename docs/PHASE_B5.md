# Phase B5 — Publication Integrity & Retraction Safety

## Goal and scope

Phase B5 adds a deterministic, source-linked publication-integrity layer. Its
purpose is to prevent retracted publications, publication-integrity notices,
and records under an expression of concern from appearing as ordinary clinical
evidence or Key Evidence. It is research-support infrastructure, not a claim
about clinical validity, misconduct, correction severity, or causality.

B5 is additive. B2 clinical relevance, B3 study assessment, and B4 clinical
extraction keep their existing meanings. A record can remain `direct` under B2
while receiving `publication_integrity.final_decision=excluded_integrity`.

## Source authority and inference boundary

The only authority is structured PubMed EFetch metadata retained on the
record:

- raw publication type labels;
- `CommentsCorrections` and its raw `RefType`;
- related PMID when supplied by PubMed;
- structured citation text (`RefSource`);
- a related DOI only if a structured DOI element is actually present.

The current PubMed DTD defines `CommentsCorrections` as `RefSource`, optional
PMID, and optional Note; it does not expose a separate related DOI in the normal
content model. B5 therefore leaves `related_doi=null` rather than extracting a
DOI from citation prose. The implemented `RefType` vocabulary follows the
[official PubMed DTD](https://dtd.nlm.nih.gov/ncbi/pubmed/doc/out/230101/el-CommentsCorrections.html)
and the direction of notice relationships follows the
[NCBI PubMed data-provider guidance](https://www.ncbi.nlm.nih.gov/books/NBK3828/table/publisherhelp.Tc/).

Title and abstract words never create an integrity signal. `no_signal` means:

> No publication-integrity warning was found in the retained PubMed metadata.

It does not mean verified, valid, safe, or free of publication problems.

## Typed taxonomy

Integrity status:

- `no_signal`
- `corrected_or_updated`
- `expression_of_concern`
- `retracted`
- `unknown`

Record role is independent:

- `primary_article`
- `correction_notice`
- `retraction_notice`
- `expression_of_concern_notice`
- `other_integrity_notice`
- `unknown`

Every normalized relation retains the normalized relationship, raw `RefType`,
related PMID/DOI when explicitly present, citation text, source field, rule ID,
and rule version. Every assessment records status, role, review requirement,
report eligibility, reason codes, human reason, structured signals, related
records, source, rule ID/version, and final decision.

## Precedence and conflicts

The centralized rule `PUBMED_PUBLICATION_INTEGRITY` version `1.0` applies:

```text
retracted
> expression_of_concern
> corrected_or_updated
> no_signal
```

Input relations are normalized, exactly duplicated relations are removed, and
the result is sorted before assessment. All distinct signals remain in the
audit. Unknown future `RefType` values and useful incomplete relations do not
crash parsing; they yield `needs_review=true`. Multiple known severity states
activate `CONFLICTING_STRUCTURED_SIGNALS`, retain every signal, and resolve by
the same order independent of XML order. Official non-integrity relations such
as comments, citations, datasets, and reprints are retained but do not create a
publication-integrity warning.

## Eligibility policy

- A retracted original remains in candidate JSON with its B2 decision intact,
  but it is not assessed/ranked as ordinary evidence and is displayed only in
  the integrity-warning section.
- A retraction, correction, expression-of-concern, or other integrity notice is
  never treated as an independent completed clinical study.
- An expression of concern sets `needs_review=true`, is report-ineligible for
  ordinary evidence, and remains visible as a warning.
- A corrected, updated, or republished primary article may remain eligible when
  no stronger signal exists. Its correction warning is shown without inferring
  whether the correction is minor or major.
- Unknown or genuinely conflicting integrity metadata is conservatively
  excluded from ordinary evidence and retained for review.
- Integrity filtering happens before B3 assessment and ranking. The report
  limit is filled from the next eligible ranked candidates, so an integrity
  exclusion does not consume a visible evidence slot.

Integrity never changes relevance class, relevance score, evidence tier,
clinical extraction, or named ranking components.

## Persistence and rendering

The B5 candidate snapshot schema is `b5`. JSON preserves raw normalized
relations, complete integrity assessment, final decision, and an explicit
`publication_integrity_warnings` placement for excluded records. Such records
receive no fabricated B3/B4 assessment or ranking audit.

Markdown and standalone HTML share the same candidate and selected lists:

- integrity-excluded records appear once in a concise warning section;
- corrected eligible primary articles show a neutral warning near the title;
- related PubMed/DOI links are emitted only when identifiers exist;
- important warnings are visible rather than hidden in technical details;
- HTML escapes titles, citations, identifiers, reasons, and source text;
- JSON remains the complete audit source of truth.

## Controlled fixture and evaluator

`tests/fixtures/b5_publication_integrity/` is a synthetic, checksummed,
PubMed-EFetch-shaped controlled regression set. Its nine unique records cover:

1. retracted original;
2. retraction notice;
3. expression-of-concern original;
4. expression-of-concern notice;
5. corrected original;
6. correction notice;
7. corrected/republished record;
8. ordinary negative control whose free text contains integrity words;
9. unknown, incomplete, duplicated, and conflicting relations.

Expected labels are separate from source XML. The manifest fixes membership,
source authority, adjudication policy, and SHA-256 checksums. The fixture is not
an external gold standard and no fixture PMID or topic appears in production
rules.

## Acceptance gates and release result

- Focused B5 suite: 12 passed, repeated deterministically.
- Canonical offline suite: 225 passed.
- Frozen B2.2B reviewer replay: 10/10 reproduced.
- B4.2 evaluator: 24/24 relevance and study-design classifications; all
  development, holdout, per-topic, extraction, ranking, placement, provenance,
  and renderer gates passed.
- B4.2 live-regression replay: 8/8 passed offline.
- Malformed, unsupported effect/safety, provenance, duplicate placement,
  selected disappearance, ranking reconstruction, renderer disagreement, and
  integrity leakage failures: zero.

All automated gates are offline and deterministic. The bounded live smoke is
reported separately because current network metadata can change. On 2026-08-27
it passed with one structured retraction/EOC notice correctly excluded and one
ordinary record retained; false-positive flags, integrity leakage into Key
Evidence, duplicate/disappeared placements, renderer disagreements, and
provenance failures were all zero.

## Limitations and Phase B6 boundary

PubMed metadata may be incomplete or delayed. B5 does not consult publisher
pages, Crossref, Retraction Watch, full text, citation networks, or regulatory
sources. It does not assess why a correction or retraction occurred and does
not infer clinical significance.

Phase B6 may add explicit, read-only comparison of two compatible saved
snapshots to report longitudinal evidence changes. Scheduling, automatic
baseline discovery, report-history databases, email, and clinical
interpretation remain outside that boundary.
