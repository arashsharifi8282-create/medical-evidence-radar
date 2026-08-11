# Medical Evidence Radar

Phase A fetches and transparently ranks recent PubMed evidence. Phase B1 adds
explainable medical concept normalization from PubMed MeSH metadata and the
official public NLM RxNorm API.

## Scope

- **Source:** PubMed only (EUtils API)
- **Topic:** any free-text PubMed topic (the default is `GLP-1-based therapies`)
- **Goal:** fetch 10 recent results, normalize them into `Article` records, classify and rank evidence, and group articles into report sections
- **Topic expansion:** discover recurring MeSH headings and author keywords; accepted and rejected terms are stored for the topic without changing the original retrieval query
- **Persistence:** optional local JSON snapshot + Markdown report + standalone HTML report + topic-profile JSON (no database, no hosting)
- **Concept normalization:** retain PubMed MeSH identifiers and normalize only accepted discovered terms against RxNorm, preserving unresolved terms
- **Safe relationship:** Phase B1 emits only `ARTICLE_MENTIONS_CONCEPT`; it never infers treatment, causality, efficacy, safety, or clinical associations

Out of scope for this slice: UMLS, SNOMED CT, Mondo, LLMs, knowledge graphs,
clinical inference, FastAPI, databases, email, Docker, frontend, web app, and deployment.

## Setup

```bash
pip install -r requirements.txt
```

## Usage

Fetch and print the 10 most recent articles for the default query:

```bash
python -m app.sources.pubmed.cli
```

Fetch, rank, print, **and save** a JSON snapshot, a Markdown report, a standalone
HTML report, and a topic profile locally:

```bash
python -m app.sources.pubmed.cli --save
```

When `--save` is used, files are named from a filesystem-safe slug of the exact
search query:

- `data/raw/pubmed/<query_slug>.json` — machine-readable snapshot
- `reports/pubmed/<query_slug>.md` — human-readable report
- `reports/pubmed/<query_slug>.html` — standalone HTML report
- `data/topic_profiles/<topic_slug>.json` — incrementally merged discovered-term profile
- `data/concepts/<topic_slug>.json` — latest per-topic normalized concepts and article links

If a query-named file already exists, the new run gets a timestamp suffix (for
example, `<query_slug>_YYYYMMDD_HHMMSS.json`) instead of overwriting it. Generated
file paths, including the per-topic concept file, are printed to the terminal.

Pass a specific topic with `--topic`; the exact free-text topic is sent to PubMed
and is also used for the transparent relevance score:

```bash
python -m app.sources.pubmed.cli --topic "GLP-1 receptor agonists for obesity" --save
```

To open the HTML report, simply double-click the file or open it in any browser:

```bash
start reports/pubmed/<query_slug>.html
```

The HTML report is fully self-contained: it uses inline CSS only, with no
external CDN, JavaScript, web server, or frontend framework. All article content
is HTML-escaped for safe display.

### JSON snapshot structure

```json
{
  "topic": "GLP-1-based therapies",
  "query": "GLP-1-based therapies",
  "fetched_at": "2026-08-10T09:30:00",
  "articles": [
    {
      "pmid": "38522001",
      "title": "...",
      "abstract": "...",
      "authors": ["Smith JA", "Chen ML"],
      "journal": "Diabetes care",
      "publication_date": "2024-06-01",
      "publication_date_raw": "2024 Jun",
      "publication_types": ["Journal Article", "Systematic Review"],
      "doi": "10.2337/dc24-0123",
      "pubmed_url": "https://pubmed.ncbi.nlm.nih.gov/38522001/",
      "source": "pubmed"
    }
  ],
  "normalized_concepts": [
    {
      "concept_id": "D000093742",
      "vocabulary": "mesh",
      "preferred_label": "Glucagon-Like Peptide-1 Receptor Agonists",
      "original_term": "Glucagon-Like Peptide-1 Receptor Agonists",
      "concept_type": "mesh_concept",
      "match_method": "source_metadata",
      "confidence": 1.0,
      "supporting_pmids": ["38522001"],
      "source_fields": ["mesh"]
    }
  ],
  "article_concept_links": [
    {
      "relationship": "ARTICLE_MENTIONS_CONCEPT",
      "pmid": "38522001",
      "concept_id": "D000093742",
      "source_field": "mesh",
      "match_method": "source_metadata",
      "confidence": 1.0,
      "evidence_level": "systematic_review"
    }
  ]
}
```

Each article also retains `mesh_descriptors` with descriptor text, MeSH UI,
`major_topic`, and `supporting_pmid` directly from EFetch XML.

### Markdown report structure

Each report includes:

- Report title
- Fetch timestamp
- Article title
- Publication date
- Publication types
- DOI
- Clickable PubMed URL
- Abstract (when available)
- A `Normalized medical concepts` section showing identifier, vocabulary,
  preferred name, original term, confidence, supporting PMIDs, and match method

### HTML report structure

The standalone HTML report is generated directly from normalized `Article`
data (not by converting Markdown). It includes:

- A header with the topic, fetch timestamp, and article count
- One source card per article showing:
  - Title
  - Publication date as listed by PubMed
  - Publication types
  - DOI
  - Clickable PubMed link
  - Abstract (when available)
- Inline CSS only — no external CDN, JavaScript, or frameworks
- All article content safely escaped with `html.escape`

### Evidence ranking and topic expansion

Phase A uses deterministic, explainable rules—there is no LLM or opaque model:

- Evidence levels are classified from PubMed publication types: guideline, systematic review/meta-analysis, randomized controlled trial, observational study, narrative review/expert opinion, or other.
- Each article receives evidence, lexical relevance, and overall scores, plus reasons and limitations.
- Reports are divided into `Key evidence`, `Important updates`, and `Exploratory evidence`; future journal-issue dates are kept out of the key-evidence section.
- MeSH headings and author keywords occurring in at least two fetched articles are scored using document frequency, evidence quality, recency, and topic overlap. Terms are accepted or rejected transparently and merged into `data/topic_profiles` across runs.

### Phase B1 concept normalization

- PubMed MeSH descriptors are accepted only from EFetch source metadata and use
  the supplied MeSH UI with confidence `1.0` and match method `source_metadata`.
- Only Phase-A **accepted** discovered terms are sent to the public RxNorm API.
- RxNorm lookup uses exact matching first, then normalized matching. A term is
  classified as `drug` only when RxNorm confirms an RXCUI.
- Distinct official RXCUIs remain distinct (for example, branded and clinical
  drug concepts are not collapsed into an ingredient).
- Failed or empty RxNorm lookups produce an `unresolved` concept instead of
  deleting or guessing the term. Transport failures add a clear warning while
  PubMed reports and MeSH concepts are still saved.
- RxNorm responses, including empty responses, are cached by normalized term in
  `data/cache/rxnorm/`; no API key is used or required.
- The only relationship is `ARTICLE_MENTIONS_CONCEPT`. `TREATS`, `CAUSES`,
  `IMPROVES`, `REDUCES_RISK`, and `ASSOCIATED_WITH` are never produced.

Programmatic use:

```python
from app.sources.pubmed.cli import fetch_top_recent, save_results

from app.services.evidence import rank_articles
from datetime import datetime

articles = fetch_top_recent(query="GLP-1-based therapies", retmax=10)
ranked = rank_articles(articles, datetime.now(), topic="GLP-1-based therapies")
json_path, md_path, html_path, profile_path = save_results(
    ranked,
    topic="GLP-1-based therapies",
    query="GLP-1-based therapies",
)
print(f"Saved: {json_path}, {md_path}, {html_path}, {profile_path}")
```

## Architecture

```
app/
  models/article.py          # Normalized Article dataclass
  services/normalizer.py     # EFetch XML -> Article (pure, no I/O)
  models/assessment.py        # EvidenceAssessment and RankedArticle dataclasses
  models/topic_profile.py     # CandidateTerm and TopicProfile dataclasses
  models/concept.py           # NormalizedConcept and safe article-link models
  services/evidence.py        # Rule-based evidence classification and ranking
  services/topic_expansion.py # MeSH/keyword discovery and profile persistence
  services/concept_normalization.py # Source-backed MeSH/RxNorm normalization
  services/persistence.py    # JSON snapshot + Markdown + HTML report writers
  sources/pubmed/client.py   # ESearch / ESummary / EFetch HTTP client
  sources/pubmed/cli.py      # Orchestrator: ESearch -> EFetch -> normalize -> optional save
  sources/rxnorm/client.py    # Public RxNorm exact/normalized lookup + local cache
tests/
  fixtures/                  # Offline captured responses
  test_normalizer.py         # XML -> Article mapping tests
  test_client.py             # Client tests with fake transport
  test_cli.py                # End-to-end slice test (offline)
  test_evidence.py            # Evidence classification, scoring, and triage
  test_topic_expansion.py     # Candidate-term discovery and scoring
  test_topic_profile_storage.py # Topic profile round-trip and merging
  test_persistence.py        # JSON/Markdown/HTML persistence tests (tmp_path, offline)
  test_rxnorm_client.py       # Fake-transport RxNorm matching and cache tests
  test_concept_normalization.py # MeSH/RxNorm normalization and edge safety tests
```

## Retrieval path

1. **ESearch** — find PMIDs for the query, sorted by publication date (newest first).
2. **EFetch** — fetch full records (title, abstract, authors, DOI, dates, publication types) as XML.
3. **Normalize** — parse XML with `xml.etree.ElementTree` into `Article` records.
4. **Assess and rank** — apply deterministic evidence-level, relevance, and recency-aware triage rules.
5. **Expand the topic** — score recurring MeSH headings and author keywords without modifying the original query.
6. **Normalize concepts** — retain source MeSH UIs and check accepted terms with
   exact-first RxNorm lookup; preserve unconfirmed terms as unresolved.
7. **Persist (optional)** — with `--save`, write a JSON snapshot, Markdown and
   HTML reports, the merged topic profile, and a per-topic concept file.

`ESummary` is available on the client but is **not** used in the primary orchestration path.

## Date handling

- Raw PubMed date text is always preserved in `publication_date_raw`.
- `publication_date` is set only when a precise ISO date can be determined:
  - Year + Month + Day → `date(year, month, day)`
  - Year + Month → `date(year, month, 1)`
- Year-only, season-only, or ambiguous dates (e.g. `2024 Mar-Apr`) → `publication_date = None`. No day or month is ever invented.

## Testing

```bash
pytest
```

All automated tests run offline using captured PubMed/RxNorm fixtures, fake HTTP
transports, and `tmp_path`; no automated test makes a live network call.

## Phase B1 live smoke test

To verify real-world behavior against PubMed (not part of the automated suite):

```bash
python -m app.sources.pubmed.cli --topic "losartan efficacy and safety in hypertension" --save
```

## Rate limits

NCBI EUtils recommends no more than 3 requests per second. The PubMed client
sleeps 0.34s between outbound calls by default. RxNorm uses its public API and
local response caching to avoid repeated requests for the same term.

## Future phases

Clinical relationship inference, graph analysis, LLM-assisted synthesis,
database storage, web application, email delivery, Docker, and deployment are
intentionally not part of Phase B1.