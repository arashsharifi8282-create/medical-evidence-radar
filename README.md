# Medical Evidence Radar

Phase A: fetch recent PubMed articles for a free-text topic, normalize them locally,
rank them with transparent evidence rules, discover recurring topic terms, and
persist the results as local reports and a topic profile.

## Scope

- **Source:** PubMed only (EUtils API)
- **Topic:** any free-text PubMed topic (the default is `GLP-1-based therapies`)
- **Goal:** fetch 10 recent results, normalize them into `Article` records, classify and rank evidence, and group articles into report sections
- **Topic expansion:** discover recurring MeSH headings and author keywords; accepted and rejected terms are stored for the topic without changing the original retrieval query
- **Persistence:** optional local JSON snapshot + Markdown report + standalone HTML report + topic-profile JSON (no database, no hosting)

Out of scope for this slice: AI, FastAPI, database, email, Docker, frontend, web app, AI summarization.

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

When `--save` is used, three timestamped files are created:

- `data/raw/pubmed/pubmed_YYYYMMDD_HHMMSS.json` — machine-readable snapshot
- `reports/pubmed/pubmed_YYYYMMDD_HHMMSS.md` — human-readable report
- `reports/pubmed/pubmed_YYYYMMDD_HHMMSS.html` — standalone HTML report
- `data/topic_profiles/<topic_slug>.json` — incrementally merged discovered-term profile

The timestamp in the report filenames ensures runs at different times do not
overwrite one another. All four created file paths are printed to the terminal.

Pass a specific topic with `--topic`; the exact free-text topic is sent to PubMed
and is also used for the transparent relevance score:

```bash
python -m app.sources.pubmed.cli --topic "GLP-1 receptor agonists for obesity" --save
```

To open the HTML report, simply double-click the file or open it in any browser:

```bash
start reports/pubmed/pubmed_YYYYMMDD_HHMMSS.html
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
  ]
}
```

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
  services/evidence.py        # Rule-based evidence classification and ranking
  services/topic_expansion.py # MeSH/keyword discovery and profile persistence
  services/persistence.py    # JSON snapshot + Markdown + HTML report writers
  sources/pubmed/client.py   # ESearch / ESummary / EFetch HTTP client
  sources/pubmed/cli.py      # Orchestrator: ESearch -> EFetch -> normalize -> optional save
tests/
  fixtures/                  # Offline captured responses
  test_normalizer.py         # XML -> Article mapping tests
  test_client.py             # Client tests with fake transport
  test_cli.py                # End-to-end slice test (offline)
  test_evidence.py            # Evidence classification, scoring, and triage
  test_topic_expansion.py     # Candidate-term discovery and scoring
  test_topic_profile_storage.py # Topic profile round-trip and merging
  test_persistence.py        # JSON/Markdown/HTML persistence tests (tmp_path, offline)
```

## Retrieval path

1. **ESearch** — find PMIDs for the query, sorted by publication date (newest first).
2. **EFetch** — fetch full records (title, abstract, authors, DOI, dates, publication types) as XML.
3. **Normalize** — parse XML with `xml.etree.ElementTree` into `Article` records.
4. **Assess and rank** — apply deterministic evidence-level, relevance, and recency-aware triage rules.
5. **Expand the topic** — score recurring MeSH headings and author keywords without modifying the original query.
6. **Persist (optional)** — with `--save`, write a JSON snapshot, a Markdown report, a standalone HTML report, and the merged topic profile.

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

All tests run offline using captured fixtures and `tmp_path`; no live network calls.

## Phase-A live smoke test

To verify real-world behavior against PubMed (not part of the automated suite):

```bash
python -m app.sources.pubmed.cli --topic "GLP-1 receptor agonists for obesity" --save
```

## Rate limits

NCBI EUtils recommends no more than 3 requests per second. The client sleeps 0.34s between outbound calls by default.

## Future phases

Graph analysis, LLM-assisted synthesis, database storage, web application,
email delivery, Docker, and deployment are intentionally not part of Phase A.