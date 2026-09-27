# Phase B7 — Research Checkpoint Package

**Historical checkpoint status (2026-09-26): research complete; specification
not yet written.**
**Date of record: 2026-09-26. Authorizing context: the Phase B7 master prompt
(research/specification-only assignment; hard approval gate prohibits
production implementation, B5/B6 changes, commits, and pushes).**

This file is a durable handoff artifact. It preserves the completed Phase A
(repository audit) and Phase B (official-source research) outputs of the B7
assignment so a later agent can produce the remaining deliverables without
re-running repository verification or external source research. It is a
research record, not an approved specification. It does not authorize
implementation. **Supersession note:** the continuation subsequently produced
approved B7 scope, implementation, fixtures/tests, M0 verification, RTM, and
controlled D6 attestation evidence in the uncommitted working tree. This file
remains a historical research record; its “remaining” and no-implementation
statements below describe the original assignment state only.

---

## 0. What is complete and what remains

Completed and recorded here:

- **Deliverable A — Repository audit** (§1).
- **Deliverable B — Official source research & benchmark matrix** for FDA,
  EMA, WHO, NICE (§3, §4), based on primary official documentation fetched
  2026-09-26, with VERIFIED/UNVERIFIED tagging per claim.

Historical remaining work (owned by the continuation task at the time):

- Deliverable C — B7 MVP scope alternatives and a single recommended scope
  (§5 of this file pre-stages the candidate scopes and the recommendation
  rationale; the continuation must formalize and defend it).
- Deliverable D/E — proposed architecture; data, identity, provenance and
  version contracts (§6 pre-stages design decisions).
- Deliverable F — `docs/PHASE_B7_PROPOSED.md` with the 23 required sections
  (problem statement … open decisions), marked PROPOSED.
- Deliverable G — `docs/PHASE_B7_RTM.md` (follow `docs/PHASE_B6_RTM.md`
  table format; statuses must be "proposed", never "pass").
- Deliverable H — offline fixture and test strategy (embed in the spec).
- Deliverable I/J/K — B5/B6 compatibility assessment; risks/limitations/
  unresolved decisions; incremental implementation milestones.
- Deliverable L — final approval checklist, plus the roadmap-maintenance
  proposal (§7 of this file) and the final report answering the master
  prompt's 14 questions.

Continuation constraints (unchanged from the master prompt): no production
code, no new source adapters, no B5/B6 behavior changes, no dependency
installation, no staging/commit/push, stop at the approval gate. New
documentation files only. Preserve all existing dirty/untracked state.

---

## 1. Repository audit (verified 2026-09-26)

- Branch `master`, HEAD `2640a76080e7b393aa5a67824cd312fc74f5c925`, identical
  to tag `v0.6.0` (Phase B6 release commit). Tags present: `v0.4.2`,
  `v0.5.0`, `v0.6.0`. Branch is up to date with `origin/main`. A local branch
  `integration/b6-remote-integration` exists.
- Canonical suite re-run locally: `269 passed in 4.82s` — the documented
  baseline ("269 passed, including 44 Phase B6 tests") is verified.
- Preserved dirty state (must remain untouched): modified
  `data/concepts/losartan_efficacy_and_safety_in_hypertension.json` and
  `data/topic_profiles/losartan_efficacy_and_safety_in_hypertension.json`;
  untracked `PROJECT_DOCUMENTATION.md`, `docs/PROJECT_FUTURE_ROADMAP.md`,
  `opencode.json`, `opencode.jsonc`, and 8 generated concept/topic-profile
  JSON artifacts under `data/`.
- Dependencies: `requirements.txt` contains only `requests>=2.31.0` and
  `pytest>=8.0.0`. B7 design must not assume new runtime dependencies.

### Architecture conventions B7 must follow (from actual code)

- **Models**: frozen dataclasses in `app/models/` with deliberately minimal
  fields and explicit `None`/unknown semantics (`app/models/article.py`,
  `app/models/integrity.py`). Rule identifiers and versions travel with
  derived data (`rule_id`, `rule_version`, e.g. `PUBMED_COMMENTS_CORRECTIONS`
  `1.0`, `PUBMED_PUBLICATION_INTEGRITY` `1.0`).
- **Clients**: transport-agnostic; the constructor takes an injectable
  `requests.Session` so tests substitute fakes without network
  (`app/sources/pubmed/client.py`, `app/sources/rxnorm/client.py`). Outbound
  calls use `timeout=30`, `raise_for_status()`, and a politeness delay
  (`DEFAULT_POLL_DELAY = 0.34`, NCBI 3 req/s rule). RxNorm persists response
  caches under `data/cache/rxnorm/` keyed by content hash; caches are local
  audit outputs, not tracked files.
- **Persistence**: `app/services/persistence.py` `build_snapshot` emits the
  `b5` snapshot dict (`schema_version: "b5" | "legacy"`); files written with
  `json.dumps(..., indent=2, ensure_ascii=False) + "\n"` under `data/raw/`,
  `reports/`; filesystem-safe query slugs (`_query_slug`, Unicode-preserving,
  Windows-reserved-name fallbacks).
- **B6 comparison** (`app/services/evidence_diff.py`, 781 lines): module
  constants `COMPARISON_SCHEMA_VERSION = "b6/1.0"`,
  `ARTICLE_IDENTITY_POLICY_VERSION = "1.0"`,
  `SNAPSHOT_COMPATIBILITY_POLICY_VERSION = "1.0"` (accepted set `{"b5"}`),
  `COMPARABILITY_POLICY_VERSION = "1.0"`,
  `COMPARISON_PRIORITY_POLICY_VERSION = "1.0"`. Fail-closed
  `ComparisonError` codes: `snapshot_not_found`, `snapshot_unreadable`,
  `malformed_snapshot`, `unsupported_schema_version`, `duplicate_pmid`,
  `incomparable_snapshots`. Identity is canonical stripped PMID only; no
  DOI/title/fuzzy matching. CLI `python -m app.services.evidence_diff BASE
  TARGET --out-dir reports/evidence_diff`; missing/invalid inputs exit 2
  with no success artifacts. Canonical JSON uses `sort_keys=True`; raw and
  semantic SHA-256 snapshot IDs; `change_id` = sha256[:16] of canonical
  change tuple. Priorities 1–8 (1 integrity … 8 comparability), tie-break
  `(category, change_type, pmid, field_path)`.
- **Versioned policy config**: `config/report_policy.json` carries
  `policy_id`, `schema_version`, `policy_version`, `scope`, `defaults`,
  `rules`. It already lists `reserved_official_sources: ["FDA", "EMA",
  "WHO", "NICE", "authoritative_guidelines"]` — a declared-but-unactivated
  extension point. B7 must not silently activate it; activation is part of
  what the B7 approval gate covers.
- **Fixtures/tests**: offline only; fake transports; `tmp_path`; fixture
  directories carry `manifest.json` with `fixture_id`, `schema_version`,
  `source_authority` provenance note, `record_count`, record identifiers,
  and SHA-256 `checksums` (see `tests/fixtures/b5_publication_integrity/`).
  Anti-overfitting rules: no fixture identifiers, PMIDs, topic strings, or
  expected values in production logic.
- **Documentation format**: phase docs use numbered sections with normative
  language; RTM is a single table `Req ID | Requirement | Spec |
  Implementation | Test(s) | Status` (see `docs/PHASE_B6_RTM.md`).

### Roadmap findings

- `docs/PROJECT_FUTURE_ROADMAP.md` (untracked; preserve status) marks B7
  `PROPOSED` with direction "Official regulatory and guideline sources such
  as FDA, EMA, WHO, NICE, and selected guidelines" and required dependencies:
  authority-specific provenance, licensing, schema, normalization, and update
  contracts. Safety boundary: never represent a source mention as approval,
  recommendation, equivalence, or applicability beyond its exact jurisdiction
  and text.
- **Stale checkpoint confirmed**: the roadmap's verification record and phase
  table still describe B6 as `APPROVED_NEXT` with "No implementation commit
  or release tag; docs/PHASE_B6.md is absent at the verified HEAD". This is
  superseded by verified Git evidence (v0.6.0 tag at HEAD; `docs/PHASE_B6.md`
  present; 269 tests passing). A minimal roadmap correction is a required B7
  deliverable (see §7), applied only with approval, preserving the
  roadmap's superseded-decision protocol.
- Roadmap open questions that B7's spec must answer: "Which official
  sources, document types, jurisdictions, and update mechanisms are in the
  exact B7 scope?" — that answer is staged in §5 below and must be finalized
  as the MVP recommendation.

---

## 2. Research method and trust boundaries

Four parallel research passes were executed 2026-09-26 against primary
official sources only (open.fda.gov / api.fda.gov / federalregister.gov;
ema.europa.eu / ec.europa.eu / eur-lex.europa.eu; who.int / iris.who.int;
nice.org.uk / api.nice.org.uk). Every load-bearing claim below is tagged
VERIFIED (official page or live first-party API response fetched during
research) or UNVERIFIED (assumption / blocked / inferred). `www.fda.gov` and
`accessdata.fda.gov` blocked automated access from the research environment
(Akamai 403); `iris.who.int` had a ~45-minute connectivity outage mid-session
(annotated inline where it matters). Nothing below may be presented in the
specification as a legal determination; licensing findings are documented
source terms, not legal advice.

---

## 3. Source comparison matrix (summary)

Full per-authority detail is in §4; this matrix is the decision surface.

| Dimension | FDA (openFDA Drugs@FDA) | EMA (JSON bulk data) | WHO (IRIS/DSpace) | NICE (Syndication API) |
|---|---|---|---|---|
| Role | Regulator (US) | Regulator (EU centralized) | Global normative guidance | Guideline/HTA body (England/Wales) |
| Official machine access | Documented JSON API + daily bulk ZIP; key required (free) | Officially documented JSON report files "targeting automated systems"; no auth | DSpace 7.6 REST (HAL/JSON), anonymous read; NOT formally documented by WHO as an integration contract | Official REST API (HATEOAS), `API-Key` header |
| Verified scale | 29,350 application records; single 8.92 MB bulk partition | medicines 2,746; EPAR documents 20,224; orphan 3,310 records (live) | Not enumerated; guideline/EML records known | 2,439 published products (website counts) |
| Stable identifiers | `application_number` (NDA/ANDA/BLA pattern); submission = (type, number) | `EMEA/H/C/nnnnnn` product number; `EMA/nnnnnn/yyyy` doc codes | `10665/NNNNNN` handles; ISBN; WHO reference numbers | "Reference number" (`TA890`, `NG245`, `CG143`, `HTG694`) |
| Version/withdrawal semantics | Complete `submissions[]` history in-record; product `marketing_status` incl. `Discontinued`; submission_status only AP/TA; no per-record change feed | `medicine_status` + lifecycle date fields; `first_published_date`/`last_updated_date` per document; withdrawal/refusal fields | No documented status mechanism; prior editions remain downloadable; versioning rels exist but use unverified | Published/Last updated dates; "superseded by" notices; **API excludes previous & withdrawn versions** |
| Update signal | Dataset-level only: `meta.last_updated`, bulk `export_date`; updates Mon–Fri | File-level `meta.timestamp`, `Last-Modified`; refreshed 06:00 & 18:00 CET | Unknown; connectivity unstable | ETag/Last-Modified conditional GET; licence refresh obligations |
| Auth/rate limits | Key required: 240/min + 120,000/day keyed; 1,000/day keyless; documented | None; no documented rate limits; robots.txt explicitly `Allow`s the JSON report paths | None documented; robots.txt blocks 527 SEO bots only; no WHO terms clause on automated access | Org-only application, cyber certification (Cyber Essentials PLUS/ISO27001/DSPT), signed licence; monthly usage reporting; no published rate limits |
| Licensing (documented terms) | Public domain + CC0; attribution requested not required; carve-outs for third-party/copyrightable content; no circumvention of limits | © EMA; free reuse incl. commercial **with attribution**; third-party content and logo excluded; EUR-Lex reuse per Decision 2011/833/EU; Union Register dataset CC BY 4.0 (BETA) | © WHO; default CC BY-NC-SA 3.0 IGO for WHO-published works (non-commercial, attribution, share-alike); per-record variance ("All rights reserved" examples exist); commercial/database use needs permission | **No OGL.** NICE UK Open Content Licence (UK-only, verbatim-reproduction rule for recommendations, AI use excluded); API licence: UK free; international test £550; worldwide service £60,000/yr |
| Format suitability for this repo (JSON metadata, no PDF parsing, stdlib+requests) | Excellent (JSON, bulk single file) | Excellent (JSON; docs themselves PDF links only) | Moderate (metadata JSON plausible but shapes unverified; content is PDF) | Moderate-poor (schema behind licence; HTML/Atom/JSON by licence) |
| Integration complexity | Low | Low | Medium (unverified shapes; flaky availability observed) | High external dependency (human licensing + certification) |
| MVP suitability | **Recommended** | Strong second (defer) | Defer | Exclude pending licence decision |

---

## 4. Verified research detail per authority

### 4.1 FDA — openFDA / Drugs@FDA

Endpoint `https://api.fda.gov/drug/drugsfda.json`; docs
`https://open.fda.gov/apis/drug/drugsfda/`; fields
`https://open.fda.gov/fields/drugsfda.yaml`; terms `https://open.fda.gov/terms/`;
authentication `https://open.fda.gov/apis/authentication/`; bulk manifest
`https://api.fda.gov/download.json`.

Verified facts:

- Seven documented drug endpoints (`event`, `label`, `ndc`, `enforcement`,
  `orangebook`, `drugsfda`, `drugshortages`). Responses carry `meta`
  (disclaimer, terms, license, `last_updated`, `results{skip,limit,total}`)
  and a `results` array.
- Drugs@FDA updates **"Daily (Monday-Friday)"**; scope caveats in official
  wording: "most" products since 1939, documents mostly since 1998, "many"
  therapeutic biological products. Live totals: 29,350 records; bulk export
  is one partition `drug-drugsfda-0001-of-0001.json.zip` (8.92 MB,
  `export_date` present).
- Record fields: `application_number` (pattern `^[BLA|ANDA|NDA]{3,4}[0-9]{6}$`;
  null for unapproved drugs; CFR citation for OTC monograph products),
  `sponsor_name`, `submissions[]` (`submission_number`, `submission_type`
  [live values ORIG/SUPPL], `submission_class_code` + description,
  `submission_status` [live values only "AP"/"TA"], `submission_status_date`
  YYYYMMDD, `review_priority`, `submission_property_type`,
  `submission_public_notes`, `application_docs[]` with `id/date/title/type/url`
  — Letters, Labels, Reviews, REMS, Medication Guides etc., present only on
  some submissions), `products[]` (`product_number`, `brand_name`,
  `active_ingredients[]{name,strength}`, `dosage_form` (no standard
  vocabulary), `route`, `marketing_status` [documented values: Prescription,
  Discontinued, None (Tentative Approval), Over-the-counter], `reference_drug`,
  `reference_standard`, `te_code`), and `openfda{}` harmonization arrays
  including `rxcui`, `spl_id`, `unii`, `substance_name`, `pharm_class_epc/moa/pe/cs`.
- Rate limits (documented): **API key required** ("An API key is required to
  make all calls to the openFDA API. The key is free of charge."); without
  key 240 req/min and 1,000 req/day per IP; with key 240 req/min and
  120,000 req/day per key; `api_key` query param or basic auth; HTTPS only.
- Pagination: `skip`/`limit` with `limit` ≤ 1000 and `skip` ≤ 25,000 (exact
  API error strings verified); `search_after` exists (named in API errors;
  usage semantics UNVERIFIED — docs page 403). Bulk export is the route for
  full enumeration.
- Change/update semantics: **no documented per-record change feed**; only
  dataset-level `meta.last_updated` / manifest `export_date`. Submission
  history is embedded in each record. Prior dataset snapshots are not
  officially archived (manifest holds only current files).
- Withdrawal detection: product-level `marketing_status = "Discontinued"`
  (14,813 live entries). Richer withdrawal codes (e.g. "Completed-NDA
  withdrawn") exist in the underlying Drugs@FDA data files dictionary on
  www.fda.gov, which was unreachable — UNVERIFIED; not represented in the
  openFDA endpoint.
- Terms: public domain + CC0 1.0 dedication; "You can copy, modify,
  distribute, and perform the work, even for commercial purposes, all
  without asking permission"; attribution requested, not required
  ("Data provided by the U.S. Food and Drug Administration
  (https://open.fda.gov)"); carve-outs: copies of copyrightable works
  (document PDFs may carry third-party rights), GMDN-specific clause;
  circumventing access limits can get access restricted; as-is, no-warranty,
  data-loss liability disclaimer.
- Every response carries: "Do not rely on openFDA to make decisions regarding
  medical care … you should assume all results are unvalidated."
- Adjacent verified USG source: Federal Register API (keyless, documented
  endpoints `/documents.{format}` etc.) — candidate for future phases only.

Unverified/open: www.fda.gov data-dictionary codes; `search_after` usage;
key signup backend; `application_docs.id` typed as `date` in the official
YAML (apparent typo — treat as opaque); semantics of `review_priority`
("Pending."), `submission_property_type`, full class-code vocabulary;
historical archive absence (verified only on the manifest).

### 4.2 EMA — official JSON bulk data + RSS

Primary: "Download website data in JSON data format"
`https://www.ema.europa.eu/en/about-us/about-website/download-website-data-json-data-format`;
legal notice
`https://www.ema.europa.eu/en/about-us/about-website/legal-notice`;
robots `https://www.ema.europa.eu/robots.txt`; feeds
`https://www.ema.europa.eu/en/news-events/rss-feeds`; Union Register
`https://ec.europa.eu/health/documents/community-register/html/`.

Verified facts:

- EMA officially documents a JSON bulk-data program: "These data files
  specifically target use via automated systems"; "The files can be used by
  anyone who is programmatically fetching documents or metadata"; "EMA's
  entire website is available in JSON format for automated use"; refreshed
  **twice daily at 06:00 and 18:00 Amsterdam time**; each file begins with a
  UTC last-update timestamp. Live HTTP 200 verification of three files
  (`application/json`, current `Last-Modified`, ranged GET supported):
  medicines (2,746 records), EPAR documents (20,224), orphan designations
  (3,310).
- Observed live schema: `meta.total_records` + `meta.timestamp` (ISO-8601
  UTC); medicines records carry `name_of_medicine`, `ema_product_number`
  (`EMEA/H/C/000944` style), `medicine_status` ("Authorised"),
  `active_substance`, INN, `atc_code_human`, `therapeutic_area_mesh`,
  `therapeutic_indication`, flags (`orphan_medicine`, `biosimilar`,
  `conditional_approval`, `accelerated_assessment`, `prime_priority_medicine`),
  holder, and lifecycle dates (`opinion_adopted_date`,
  `marketing_authorisation_date`, `withdrawal_of_application_date`,
  `refusal_of_marketing_authorisation_date`,
  `withdrawal_expiry_revocation_lapse_of_marketing_authorisation_date`).
  EPAR document records carry `id`, `name`, `type`
  (`variation-report`, `overview`, …), `medicine_name`, `ema_product_number`,
  `first_published_date`, `last_updated_date`, `document_url` (PDF),
  `translations`.
- robots.txt explicitly `Allow: /*/documents/report/*.json$` (the only
  non-static Allow). No auth; no documented rate limits; no documented
  schema/URL stability contract (change log on the page begins April 2026 —
  offering appears new).
- Licensing: © EMA legal notice permits reproduction/distribution for
  non-commercial and commercial purposes "provided that EMA is always
  acknowledged as the source"; acknowledgement "must be included in each
  copy"; citations need source + access month/year; third-party content and
  the EMA logo are excluded; "the official adopted text will always prevail".
  No anti-scraping clause. EUR-Lex: reuse per Commission Decision
  2011/833/EU, CC BY 4.0 where marked, IP-protected documents excluded.
- Status/versioning: medicine-level status plus explicit
  withdrawal/refusal/expiry date fields; watermarking of documents on
  withdrawal actions; WEPAR (withdrawal EPAR) category; per-document
  `first_published_date`/`last_updated_date`; persistent product numbers and
  `EMA/nnnnnn/yyyy` committee document codes.
- Scope caveats: EMA covers **centrally authorised** products (plus some
  referrals etc.); nationally authorised medicines live in member-state
  registers; Union Register covers Commission authorisations and is **BETA**
  (its "Medicinal products dataset" is CC BY 4.0; EudraPharm was
  decommissioned June 2019 — official glossary). Document content itself is
  PDF-first; document-level `status` values include `"unknown"` (rely on
  medicine-level status).

Unverified/open: Union Register dataset schema; data.europa.eu hosting;
guideline-page effective-date conventions; PRAC-specific feed sampling;
long-term schema stability of the JSON program (no versioned contract).

### 4.3 WHO — IRIS (DSpace 7.6)

Primary: `https://iris.who.int` (and `/server/api` root, captured live);
terms `https://www.who.int/about/policies/terms-of-use`; copyright
`https://www.who.int/about/policies/publishing/copyright`; EML page
`https://www.who.int/groups/expert-committee-on-selection-and-use-of-essential-medicines/essential-medicines-lists`;
example guideline record
`https://www.who.int/publications/i/item/9789240033986`.

Verified facts:

- IRIS = "Institutional Repository for Information Sharing", "free digital
  access to the scientific and technical publications of the World Health
  Organization". Runs **DSpace 7.6**; REST root `https://iris.who.int/server/api`
  returns HAL JSON advertising `items/collections/communities/bundles/
  bitstreams/discover/browses/metadatafields` plus templated `pid`
  (`/server/api/pid/find{?id}`) and `dso`; versioning rels (`versions`,
  `versionhistories`, `atmire-versions`) present; **no `oai` rel advertised**.
  Official who.int pages already link production PDFs at
  `https://iris.who.int/server/api/core/bitstreams/{uuid}/content`.
- UI browse indexes include **Subject (MeSH)**, Issue Date, Type, and a
  "WHO Guidelines" collection; 8 UI languages.
- Identifiers observed on publication pages: ISBN (guidelines, e.g.
  978-92-4-003398-6), WHO reference numbers (`WHO/MHP/HPS/EML/2023.02`),
  product codes (`B09474`), IRIS handles `10665/NNNNNN` (legacy
  `apps.who.int/iris/handle/...` 302-redirects to iris.who.int).
- Licensing: © WHO 2021 terms — extracts usable for research/private study,
  non-commercial; substantial reproduction/translation needs prior written
  authorization; attribution with URL required. Default licence for
  WHO-published works: **CC BY-NC-SA 3.0 IGO** (non-commercial, attribution
  "[Title]. [Place]: World Health Organization; [Year]. Licence:
  CC BY-NC-SA 3.0 IGO", share-alike); **per-record variance exists**
  (the 2014 guideline handbook page shows "All rights reserved");
  commercial/database licensing requires permission; non-endorsement clause.
- Versioning/supersession: **no machine-readable status mechanism found**
  on any fetched page; prior editions remain downloadable (EML 2021/2023
  alongside 2025); no jurisdiction concept in metadata; PDF-oriented (no
  structured/XML document format).
- Operational: anonymous read; no documented rate limits; www.who.int
  robots.txt blocks 527 named bots (not mainstream crawlers), no
  Crawl-delay; **observed ~45-minute connectivity outage to iris.who.int
  during research** — availability risk is real and must shape design
  (caching, retries, snapshot-based ingestion).

Unverified/open: item-level metadata JSON shapes (`dc.*` fields), discover
search behavior and determinism, OAI-PMH existence
(`/server/oai/request` is the DSpace default but timed out unverified),
iris.who.int robots.txt, per-item DSpace versioning usage, license-variance
distribution across the catalog.

### 4.4 NICE — Syndication Service (gated)

Primary: `https://api.nice.org.uk/`;
`https://www.nice.org.uk/reusing-our-content/nice-syndication-api`;
user guide ECD10
`https://www.nice.org.uk/corporate/ecd10/chapter/using-your-api-key-to-explore-nice-content`;
licence
`https://www.nice.org.uk/reusing-our-content/nice-uk-open-content-licence`;
terms `https://www.nice.org.uk/terms-and-conditions`.

Verified facts:

- The deterministic integration route is the **NICE Syndication Service**:
  organization-only application ("not individuals"), mandatory
  cyber-security certification (Cyber Essentials PLUS, ISO27001, or NHS
  DSPT), signed licence, `API-Key` header, media types
  `text/html`, `application/atom+xml`,
  `application/vnd.nice.syndication.services+json`(+xml). Documented
  endpoints: `/services/guidance`, `/services/guidance/by-date`,
  `/services/guidance/index`, `/services/guidance/programmes`,
  `/services/guidance/taxonomy`, `/linkrels` (HATEOAS). Conditional GET
  (ETag/Last-Modified) documented. **Fees: UK free; international test
  £550; annual worldwide service licence £60,000.** Monthly usage
  reporting obliged; refresh obligations (feeds ≤24h, other ≤7d, immediate
  on NICE request).
- **The API excludes "previous versions of NICE guidance, withdrawn
  guidance"** and guidance-development material — longitudinal change
  detection would depend entirely on locally retained snapshots.
- Reuse without the API: NICE UK Open Content Licence — UK-only,
  royalty-free, but recommendations/quality statements must be "reproduced
  as originally published" (no adaptation of wording/structure); mandated
  attribution form of words; **AI/LLM training use prohibited**; outside
  the UK reuse needs prior written agreement (T&C 18.2). No OGL.
- Status/version semantics on the site: Published / Terminated / In
  consultation / In development / Deferred / Awaiting development tabs;
  "Reference number" identifiers (TA890, NG245, CG143, HTG694); Published /
  Last updated / Last reviewed dates; "Update information" chapter;
  supersession notices ("This guideline has been updated and replaced by
  NICE guideline NG245."). No numeric document versions; `/history` pages
  are development-process archives, not edition archives.
- Caveats: NICE is a guideline/HTA body (not a regulator); TA/HST
  recommendations carry a statutory NHS funding duty, other guidance is
  "actively encouraged" and explicitly "not mandatory"; jurisdiction
  England (Wales nuance unverified).

Unverified/open: API pagination/rate limits and rich JSON field schema
(documented only behind licence login); API exposure of non-published
states; per-edition archives; Dublin Core meta in page HTML; permissibility
of unlicensed programmatic website access (assume **not** permitted without
asking NICE).

**Consequence for B7**: NICE cannot be in the MVP. Any future NICE
integration is blocked on a licensing decision (application + certification
+ licence terms), not on engineering.

---

## 5. Pre-staged MVP scope decision (recommendation, requires approval)

Two-plus feasible scopes emerged from the research. The recommendation for
the specification to formalize is **Alternative A**.

**Alternative A (recommended): FDA Drugs@FDA only, one document category,
metadata-only.**
- Authority: FDA via openFDA `drug/drugsfda`. Jurisdiction: US. Document
  category: drug application records (application + submissions history +
  products + document links), *not* FAERS, *not* labels, *not* enforcement.
- Ingestion: single bulk ZIP partition (8.92 MB) via `download.json`
  manifest, or targeted `search=` queries (keyed API). Metadata-only: never
  fetch/store the linked PDFs in B7 (they may carry third-party copyright —
  store URLs and titles only). This keeps licensing inside the CC0 space.
- Identity: application record identity `(source_authority="FDA",
  document_type="drug_application", source_document_id=<application_number>)`;
  null application_number fails closed as `missing_identifier`. Version
  identity = canonical identity + dataset `export_date`/`meta.last_updated`
  + record `content_digest` (SHA-256 of canonical record bytes). Withdrawal
  represented only as source-stated `marketing_status="Discontinued"` —
  never paraphrased as "withdrawn approval".
- Why first: only candidate with (a) documented JSON contract, (b) documented
  bulk export, (c) CC0 terms covering metadata storage/redistribution, (d)
  stable documented identifiers, (e) an RxNorm `rxcui` bridge matching the
  repo's existing concept-provenance architecture, (f) zero human licensing
  gate. Limits: US-only; no per-record change feed (dataset-level
  timestamps only — local snapshots therefore carry the version history, the
  exact model B6 already uses for PubMed).

**Alternative B: EMA medicines JSON only** (centralised medicines list with
status/lifecycle dates). Comparable quality (official automated-use
program, attribution-only licensing, stable product numbers, richer status
fields) but: no rate-limit/stability contract, newer offering (change log
begins April 2026), attribution must be embedded in every persisted copy,
and EU status semantics (conditional/withdrawn/refused/expired) add policy
surface. Defer to B7.x after the FDA adapter establishes the envelope.

**Alternative C: envelope-first with a stub second adapter** — build the
generic regulatory-record envelope + normalization contract and wire both
FDA and EMA minimal adapters. Rejected for MVP: doubles licensing/provenance
policies to validate before any value is delivered; conflicts with the
master prompt's "one authority, few document categories" guidance.

**Excluded from B7 entirely**: NICE (licence gate: certification + signed
licence + fees + verbatim-reproduction and AI-exclusion terms); WHO
(metadata shapes unverified, PDF-oriented, no status mechanism, observed
availability instability — reassess after IRIS endpoint probing from a
stable network); FAERS/openFDA adverse events (anti-causation caveats make
it a distinct safety-signal product, not regulatory-document evidence);
FDA labels/orangebook/shortages (separate categories, later decisions);
Federal Register (different document genus).

---

## 6. Pre-staged contract design decisions (recommendations to formalize)

These follow from the repo audit + research and are ready to be written into
`docs/PHASE_B7_PROPOSED.md`; each remains a proposal until approved.

1. **Separate typed schema, never grafted onto b5.** New module family:
   `app/sources/regulatory/` (adapter package; first concrete adapter
   `fda_openfda.py`) and `app/models/regulatory_document.py` (frozen
   dataclass). No synthetic PMIDs; no changes to `Article`.
2. **Canonical envelope fields** (candidate set justified by verified
   metadata only): `schema_version` (`"b7/1.0"`),
   `normalization_version`, `source_authority` (`"FDA"`),
   `source_system` (`"openFDA"`), `source_document_id`
   (application_number), `document_type` (`"drug_application"`),
   `jurisdiction` (`"US"`), `title`, `sponsor_name`, `canonical_url`
   (openFDA record/API URL — deterministic construction),
   `publication_date` (latest submission status date; only if present),
   `retrieval_timestamp` (audit-only), `dataset_timestamp`
   (`meta.last_updated`/`export_date`), `document_status` (source-stated
   only: derived conservatively from `marketing_status` values with an
   explicit `needs_review` when absent/ambiguous), `documents`
   (URL/title/type/date of `application_docs`, links only),
   `products` (normalized product/ingredient/route/marketing-status),
   `submissions` (normalized history), `provenance` (endpoint URL,
   query/manifest, disclaimers, license note, rule ids/versions),
   `content_digest` (SHA-256 over canonical record), `raw_source_reference`
   (exact source field paths). Fields with no verified source metadata are
   omitted rather than invented; all candidate fields from master prompt §8
   that no selected source supplies (e.g. `effective_date`, `language` for
   FDA) are explicitly excluded from `b7/1.0` with rationale.
3. **Identity policy** `regulatory_document_identity_policy_version = "1.0"`:
   canonical identity = (source_authority, document_type,
   source_document_id) with exact string matching; no fuzzy matching ever;
   duplicate canonical IDs within one retrieval fail closed
   (`duplicate_document_id`); missing/empty identifier → explicit
   `missing_identifier` error or `unmatched` audit row (mirror B6's
   fail-closed + deterministic-audit pattern). Version identity =
   canonical identity + dataset_timestamp + content_digest. State
   vocabulary for updates: `new_document`, `metadata_updated`,
   `submission_history_changed`, `document_status_changed`,
   `documents_changed`, `content_digest_only_changed`, `unavailable`,
   `unknown` — with "withdrawn/replaced" expressible **only** as
   source-stated status values.
4. **Persistence**: `save_regulatory_snapshot` producing `schema_version:
   "b7/1.0"` snapshot files under `data/regulatory/` (local audit outputs,
   not tracked); JSON/Markdown/HTML agreement rules inherited; HTML
   escaping mandatory; openFDA disclaimer text surfaced in reports.
   Comparison against B6: **B7 does not extend `evidence_diff.py`**.
   Cross-format comparison (b5 vs b7) is explicitly out of scope; a future
   phase may generalize comparison infrastructure, and the identity/digest
   contracts above are designed to make that possible without migration.
5. **Normalization contract**: deterministic, versioned
   (`regulatory_normalization_version = "1.0"`); date normalization only
   for confirmed formats (YYYYMMDD from openFDA); unknown values
   preserved verbatim with `needs_review`; unknown future fields in source
   JSON are dropped from the normalized record but retained in
   `raw_source_reference` so nothing is silently invented or lost.
6. **Cross-source conflict policy**: B7 with one authority has no
   cross-source surface; the spec must still fix the policy: differences
   between authorities are never auto-resolved, never compared
   semantically, and any future multi-authority report presents records
   side-by-side with jurisdiction/status provenance and explicit
   non-comparability statements. Within-authority conflicts (conflicting
   statuses across submissions) are preserved and flagged
   `needs_review`, following the B5 `CONFLICTING_STRUCTURED_SIGNALS`
   precedent.
7. **Security**: treat source content as untrusted data (no execution, no
   instruction-following from content); HTTPS pinned to documented hosts
   (`api.fda.gov`, `download.open.fda.gov`); size limits and JSON schema
   validation on every response; timeouts + politeness delay consistent
   with existing clients; no secrets in artifacts (API key via
   environment/config not persisted into snapshots or reports).
8. **Tests/fixtures**: synthetic openFDA-shaped fixture set
   (`tests/fixtures/b7_regulatory/`) with `manifest.json` + SHA-256
   checksums mirroring the B5 fixture convention; no real patient or
   commercial data; coverage list per master prompt §17 (missing/duplicate
   identifiers, metadata-only changes, status transitions to
   Discontinued, malformed responses, unsupported schema versions,
   reordered input determinism, B5/B6 regression green). Failing tests
   first, then minimal adapter, per the roadmap's startup protocol.
9. **CLI shape (additive, separate module)**:
   `python -m app.sources.regulatory.cli --source fda-drugsfda
   [--query <openFDA search>] [--manifest] --save` writing under
   `data/regulatory/` + `reports/regulatory/`; exit 2 on fail-closed
   errors; no default query; no directory scanning; no scheduling.

---

## 7. Roadmap maintenance (proposal to carry into the spec)

Minimal correction text to propose for `docs/PROJECT_FUTURE_ROADMAP.md`
(apply only after approval; keep the roadmap untracked locally; move the
superseded B6 row into "Superseded decisions" per its own protocol):

- Verification record: add "2026-09-26 re-verification: HEAD
  `2640a76080e7b393aa5a67824cd312fc74f5c925` = tag `v0.6.0`; canonical
  suite 269 passed (44 B6); B6 production, fixtures, tests, and
  `docs/PHASE_B6.md`/`docs/PHASE_B6_RTM.md` present."
- Phase table B6 row: `APPROVED_NEXT` → `VERIFIED_COMPLETE` with commit/tag
  evidence; the "Phase B6 is the next approved implementation phase"
  sentence superseded by "Phase B6 is complete and released as v0.6.0."
- Decision log: add row "B6 complete, released v0.6.0 (evidence: tag at
  HEAD, 269-passing suite) — B7 remains PROPOSED until scope approval; no
  later phase authorized."

---

## 8. Unresolved decisions that genuinely require product approval

1. Approve Alternative A MVP scope (FDA Drugs@FDA, drug-application records
   only, US, metadata-only) — or select B/C.
2. Approve licensing posture: storage/redistribution of openFDA metadata
   under CC0 with optional attribution; explicit decision **not** to fetch
   third-party-copyright document PDFs in B7.
3. Approve the `b7/1.0` schema field list and the identity/version policy
   version pin (§6.2–6.3).
4. Approve B7 non-extension of `evidence_diff.py` and the "no cross-format
   comparison" boundary.
5. Approve the roadmap correction text (§7) and its application method.
6. Decide whether the live openFDA key (free) will be obtained for
   real-source verification, or whether release ships with fixture-only
   verification and live verification deferred.
7. (Deferred, not blocking) Whether EMA is pre-approved as the B7.x second
   authority contingent on a stability/rate-limit review.
