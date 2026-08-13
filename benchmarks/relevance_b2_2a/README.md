# B2.2A relevance benchmark

Frozen `(topic_id, PMID)` pilot for measuring B2 relevance before any rule change. `articles.jsonl` is an immutable source snapshot; `draft_labels.jsonl` contains provisional, source-grounded labels and **is not gold truth**. `adjudicated_labels.jsonl` is intentionally empty until independent human adjudication. The evaluator refuses an official baseline without valid adjudicated records.

## Topics and sampling

The pilot has 77 records: 17 `losartan_hypertension`, 36 `masld_mash_multi_intervention`, and 24 `semaglutide_obesity_safety`. The semaglutide safety pool was acquired once on 2026-08-12 using the documented query and existing PubMed client; only title/abstract metadata, not full text, was frozen. The MASLD/MASH historical query is preserved verbatim with all 12 OR interventions; it is never reduced to resmetirom.

On 2026-08-13, B2.2A.1 added seven **provisional draft** class-level losartan records from the one-time 40-candidate `losartan_class_candidate_pool.jsonl` acquisition. Its exact query, returned PMID order, total count, acquisition time, and raw EFetch SHA-256 are retained in `topics.json`. Class provenance is benchmark-only: NLM MeSH `D047228` (*Angiotensin II Type 1 Receptor Blockers*) has an official scope note explicitly including losartan and `D057911` (*Angiotensin Receptor Antagonists*) as parent. RxClass returned no approved ATC/MED-RT `has_member`, `isa`, or `part_of` link for losartan RXCUI `52175`; therefore this MeSH provenance **does not alter the production rule**, which continues to consume only approved RxClass structural relationships.

## Label policy

`direct` requires substantive focus on a requested intervention and requested condition/population, clinical coherence, and more than a background/list/comparator/standard-care mention. Study design or evidence level does not determine relevance: protocols, models, and reviews can be direct if genuinely target-focused.

`class_level` requires a structurally verified parent class, substantive class focus, and the condition. Indication, mechanism, physiologic effect, ingredient and lexical similarity never prove membership. For the seven losartan-class draft examples, official NLM MeSH is **benchmark-only** provenance: `D047228` (*Angiotensin II Type 1 Receptor Blockers*) has a scope note explicitly including losartan and has parent `D057911` (*Angiotensin Receptor Antagonists*). RxClass lookup for losartan RXCUI `52175` returned no approved ATC/MED-RT `has_member`, `isa`, or `part_of` relationship; therefore production does **not** currently support this MeSH provenance and no production rule was changed. `contextual` covers useful but insufficiently focused material: incidental/background or author-keyword-only support, comparator-only target use, broad target-list reviews, other-intervention focus, and target-matched preclinical evidence for a human question. `irrelevant` means an essential target is absent or the primary subject is unrelated; preclinical work can be irrelevant when clinical applicability and target-condition relation are absent.

The B2.2A.1 MeSH-supported examples remain `draft`, not adjudicated, and are deliberately reported as provisional until independent human review. `adjudicated_labels.jsonl` remains empty.

For OR topics, any substantively focused requested intervention may be direct and the complete matched set is recorded. AND topics require all required interventions. `needs_review` is a status/uncertainty flag, not a fifth relevance class: ambiguous metadata is not forced into a class.

## Workflow

1. A reviewer creates draft/needs-review labels independently of the B2 prediction and score.
2. A second reviewer independently reviews disputed/uncertain records.
3. Record adjudication notes and set only resolved records to `adjudicated`.
4. Run `python scripts/evaluate_relevance_benchmark.py --articles ... --labels ... --output ...`.

SHA-256 values bind a label to its frozen source snapshot. Controlled reason codes are enumerated in `schema.json`.