"""Local file persistence for fetched PubMed results.

This module is pure: it takes normalized :class:`Article` records plus metadata
and writes machine-readable JSON snapshots, human-readable Markdown reports,
and standalone HTML reports to timestamped files. No network calls are made here.
"""

from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path

from app.models.article import Article

DEFAULT_JSON_DIR = Path("data/raw/pubmed")
DEFAULT_MD_DIR = Path("reports/pubmed")
DEFAULT_HTML_DIR = Path("reports/pubmed")


def _article_to_dict(article: Article) -> dict:
    """Convert an :class:`Article` into a JSON-serializable dict."""
    return {
        "pmid": article.pmid,
        "title": article.title,
        "abstract": article.abstract,
        "authors": list(article.authors),
        "journal": article.journal,
        "publication_date": (
            article.publication_date.isoformat() if article.publication_date else None
        ),
        "publication_date_raw": article.publication_date_raw,
        "publication_types": list(article.publication_types),
        "doi": article.doi,
        "pubmed_url": article.pubmed_url,
        "source": article.source,
    }


def build_snapshot(
    topic: str,
    query: str,
    fetched_at: datetime,
    articles: list[Article],
) -> dict:
    """Build the JSON snapshot payload."""
    return {
        "topic": topic,
        "query": query,
        "fetched_at": fetched_at.isoformat(),
        "articles": [_article_to_dict(a) for a in articles],
    }


def build_markdown_report(
    topic: str,
    fetched_at: datetime,
    articles: list[Article],
) -> str:
    """Build a human-readable Markdown report."""
    lines: list[str] = []
    lines.append(f"# PubMed Report: {topic}")
    lines.append("")
    lines.append(f"**Fetch timestamp:** {fetched_at.isoformat()}")
    lines.append("")
    lines.append(f"**Articles:** {len(articles)}")
    lines.append("")
    lines.append("---")
    lines.append("")

    for i, article in enumerate(articles, start=1):
        lines.append(f"## {i}. {article.title}")
        lines.append("")
        if article.publication_date_raw:
            lines.append(
                f"- **Publication date as listed by PubMed:** {article.publication_date_raw}"
            )
        if article.publication_types:
            lines.append(f"- **Publication types:** {', '.join(article.publication_types)}")
        if article.doi:
            lines.append(f"- **DOI:** {article.doi}")
        if article.pubmed_url:
            lines.append(f"- **PubMed:** [Open in PubMed]({article.pubmed_url})")
        if article.abstract:
            lines.append("")
            lines.append(f"**Abstract:** {article.abstract}")
        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def build_html_report(
    topic: str,
    fetched_at: datetime,
    articles: list[Article],
) -> str:
    """Build a polished, standalone HTML report directly from Article data.

    All article content is escaped with :func:`html.escape`. The page uses
    inline CSS only — no external CDN, JavaScript, or frameworks.
    """
    e = html.escape
    esc_topic = e(topic)
    esc_fetched_at = e(fetched_at.isoformat())
    article_count = len(articles)

    cards: list[str] = []
    for i, article in enumerate(articles, start=1):
        esc_title = e(article.title)
        esc_date_raw = e(article.publication_date_raw)
        esc_types = e(", ".join(article.publication_types))
        esc_doi = e(article.doi)
        esc_url = e(article.pubmed_url)
        esc_abstract = e(article.abstract)

        meta_items: list[str] = []
        if esc_date_raw:
            meta_items.append(
                f'<div class="meta-item"><span class="meta-label">Publication date:</span> '
                f'<span class="meta-value">{esc_date_raw}</span></div>'
            )
        if esc_types:
            meta_items.append(
                f'<div class="meta-item"><span class="meta-label">Publication types:</span> '
                f'<span class="meta-value">{esc_types}</span></div>'
            )
        if esc_doi:
            meta_items.append(
                f'<div class="meta-item"><span class="meta-label">DOI:</span> '
                f'<span class="meta-value">{esc_doi}</span></div>'
            )
        if esc_url:
            meta_items.append(
                f'<div class="meta-item"><span class="meta-label">PubMed:</span> '
                f'<a class="meta-link" href="{esc_url}" target="_blank" rel="noopener noreferrer">'
                f"Open in PubMed</a></div>"
            )

        abstract_html = ""
        if esc_abstract:
            abstract_html = (
                f'<div class="abstract"><span class="abstract-label">Abstract:</span> '
                f'<p class="abstract-text">{esc_abstract}</p></div>'
            )

        cards.append(
            f"""<article class="card">
  <h2 class="card-title"><span class="card-index">{i}.</span> {esc_title}</h2>
  <div class="card-meta">
    {chr(10).join(meta_items)}
  </div>
  {abstract_html}
</article>"""
        )

    cards_html = "\n".join(cards)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PubMed Report: {esc_topic}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                   "Helvetica Neue", Arial, sans-serif;
      background-color: #f4f6f8;
      color: #1a202c;
      line-height: 1.6;
      padding: 2rem 1rem;
    }}

    .container {{
      max-width: 900px;
      margin: 0 auto;
    }}

    header.report-header {{
      background: linear-gradient(135deg, #1a365d 0%, #2b6cb0 100%);
      color: #ffffff;
      border-radius: 12px;
      padding: 2rem 2.5rem;
      margin-bottom: 2rem;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
    }}

    header.report-header h1 {{
      font-size: 1.75rem;
      font-weight: 700;
      margin-bottom: 0.75rem;
      letter-spacing: -0.02em;
    }}

    .header-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 1.5rem;
      font-size: 0.95rem;
      opacity: 0.95;
    }}

    .header-meta span {{
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
    }}

    .header-meta .label {{
      font-weight: 600;
      text-transform: uppercase;
      font-size: 0.75rem;
      letter-spacing: 0.05em;
      opacity: 0.8;
    }}

    .card {{
      background: #ffffff;
      border: 1px solid #e2e8f0;
      border-radius: 10px;
      padding: 1.75rem 2rem;
      margin-bottom: 1.5rem;
      box-shadow: 0 2px 6px rgba(0, 0, 0, 0.06);
      transition: box-shadow 0.2s ease;
    }}

    .card:hover {{
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
    }}

    .card-title {{
      font-size: 1.2rem;
      font-weight: 600;
      color: #1a365d;
      margin-bottom: 1rem;
      line-height: 1.4;
    }}

    .card-index {{
      color: #718096;
      font-weight: 500;
      margin-right: 0.25rem;
    }}

    .card-meta {{
      display: flex;
      flex-direction: column;
      gap: 0.4rem;
      margin-bottom: 1rem;
    }}

    .meta-item {{
      font-size: 0.92rem;
    }}

    .meta-label {{
      font-weight: 600;
      color: #4a5568;
      margin-right: 0.4rem;
    }}

    .meta-value {{
      color: #2d3748;
    }}

    .meta-link {{
      color: #2b6cb0;
      text-decoration: none;
      font-weight: 500;
    }}

    .meta-link:hover {{
      text-decoration: underline;
    }}

    .abstract {{
      background-color: #f7fafc;
      border-left: 4px solid #2b6cb0;
      border-radius: 0 6px 6px 0;
      padding: 1rem 1.25rem;
    }}

    .abstract-label {{
      font-weight: 600;
      color: #2b6cb0;
      display: block;
      margin-bottom: 0.4rem;
      font-size: 0.85rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}

    .abstract-text {{
      color: #2d3748;
      font-size: 0.95rem;
    }}

    footer.report-footer {{
      text-align: center;
      color: #718096;
      font-size: 0.85rem;
      margin-top: 2rem;
      padding-top: 1rem;
      border-top: 1px solid #e2e8f0;
    }}

    @media (max-width: 600px) {{
      body {{ padding: 1rem 0.5rem; }}
      header.report-header {{ padding: 1.5rem; }}
      .card {{ padding: 1.25rem 1.5rem; }}
      .header-meta {{ flex-direction: column; gap: 0.5rem; }}
    }}
  </style>
</head>
<body>
  <div class="container">
    <header class="report-header">
      <h1>PubMed Report: {esc_topic}</h1>
      <div class="header-meta">
        <span><span class="label">Fetched</span> {esc_fetched_at}</span>
        <span><span class="label">Articles</span> {article_count}</span>
      </div>
    </header>

    {cards_html}

    <footer class="report-footer">
      Generated locally by Medical Evidence Radar &middot; {esc_fetched_at}
    </footer>
  </div>
</body>
</html>
"""


def _timestamp_str(dt: datetime) -> str:
    """Format a datetime for use in filenames (safe for all filesystems)."""
    return dt.strftime("%Y%m%d_%H%M%S")


def save_snapshot(
    snapshot: dict,
    output_dir: Path = DEFAULT_JSON_DIR,
    fetched_at: datetime | None = None,
) -> Path:
    """Write the JSON snapshot to a timestamped file and return its path."""
    fetched_at = fetched_at or datetime.now()
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"pubmed_{_timestamp_str(fetched_at)}.json"
    path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def save_markdown_report(
    markdown: str,
    output_dir: Path = DEFAULT_MD_DIR,
    fetched_at: datetime | None = None,
) -> Path:
    """Write the Markdown report to a timestamped file and return its path."""
    fetched_at = fetched_at or datetime.now()
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"pubmed_{_timestamp_str(fetched_at)}.md"
    path.write_text(markdown, encoding="utf-8")
    return path


def save_html_report(
    html_report: str,
    output_dir: Path = DEFAULT_HTML_DIR,
    fetched_at: datetime | None = None,
) -> Path:
    """Write the HTML report to a timestamped file and return its path."""
    fetched_at = fetched_at or datetime.now()
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"pubmed_{_timestamp_str(fetched_at)}.html"
    path.write_text(html_report, encoding="utf-8")
    return path