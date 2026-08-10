"""Orchestrator for the PubMed vertical slice.

Composes ESearch -> EFetch -> normalize into a single ``fetch_top_recent``
callable. ESummary is intentionally not used in this path.

With ``--save``, the fetched results are also persisted locally as a
machine-readable JSON snapshot, a human-readable Markdown report, and a
standalone HTML report.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from app.models.article import Article
from app.services.normalizer import normalize_article, parse_pubmed_articles
from app.services.persistence import (
    DEFAULT_HTML_DIR,
    DEFAULT_JSON_DIR,
    DEFAULT_MD_DIR,
    build_html_report,
    build_markdown_report,
    build_snapshot,
    save_html_report,
    save_markdown_report,
    save_snapshot,
)
from app.sources.pubmed.client import PubMedClient

DEFAULT_QUERY = "GLP-1-based therapies"
DEFAULT_RETMAX = 10


def fetch_top_recent(
    query: str = DEFAULT_QUERY,
    retmax: int = DEFAULT_RETMAX,
    client: PubMedClient | None = None,
) -> list[Article]:
    """Fetch the ``retmax`` most recent PubMed articles for ``query``.

    ``client`` is injectable for testing; defaults to a real ``PubMedClient``.
    """
    client = client or PubMedClient()

    pmids = client.esearch(query, retmax=retmax)
    if not pmids:
        return []

    xml = client.efetch(pmids)
    return [normalize_article(elem) for elem in parse_pubmed_articles(xml)]


def save_results(
    articles: list[Article],
    topic: str = DEFAULT_QUERY,
    query: str = DEFAULT_QUERY,
    fetched_at: datetime | None = None,
    json_dir: Path = DEFAULT_JSON_DIR,
    md_dir: Path = DEFAULT_MD_DIR,
    html_dir: Path = DEFAULT_HTML_DIR,
) -> tuple[Path, Path, Path]:
    """Persist ``articles`` as a JSON snapshot, a Markdown report, and an HTML report.

    Returns the paths of the three created files.
    """
    fetched_at = fetched_at or datetime.now()

    snapshot = build_snapshot(
        topic=topic,
        query=query,
        fetched_at=fetched_at,
        articles=articles,
    )
    json_path = save_snapshot(snapshot, output_dir=json_dir, fetched_at=fetched_at)

    markdown = build_markdown_report(
        topic=topic,
        fetched_at=fetched_at,
        articles=articles,
    )
    md_path = save_markdown_report(markdown, output_dir=md_dir, fetched_at=fetched_at)

    html_report = build_html_report(
        topic=topic,
        fetched_at=fetched_at,
        articles=articles,
    )
    html_path = save_html_report(html_report, output_dir=html_dir, fetched_at=fetched_at)

    return json_path, md_path, html_path


def main(argv: list[str] | None = None) -> None:
    """CLI entrypoint: print normalized articles for the default query.

    With ``--save``, also persist a JSON snapshot, a Markdown report, and an
    HTML report.
    """
    parser = argparse.ArgumentParser(
        prog="python -m app.sources.pubmed.cli",
        description="Fetch recent PubMed articles for a fixed topic and optionally save them locally.",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save a JSON snapshot, a Markdown report, and an HTML report to local files.",
    )
    args = parser.parse_args(argv)

    articles = fetch_top_recent()
    print(f"Fetched {len(articles)} articles for query: {DEFAULT_QUERY!r}\n")
    for article in articles:
        print(f"PMID: {article.pmid}")
        print(f"Title: {article.title}")
        print(f"Journal: {article.journal}")
        print(f"Date (raw): {article.publication_date_raw!r} -> {article.publication_date}")
        print(f"Authors: {', '.join(article.authors)}")
        print(f"Types: {', '.join(article.publication_types)}")
        print(f"DOI: {article.doi}")
        print(f"URL: {article.pubmed_url}")
        print(f"Abstract: {article.abstract[:200]}{'...' if len(article.abstract) > 200 else ''}")
        print("-" * 80)

    if args.save:
        json_path, md_path, html_path = save_results(articles)
        print(f"\nSaved JSON snapshot: {json_path}")
        print(f"Saved Markdown report: {md_path}")
        print(f"Saved HTML report: {html_path}")


if __name__ == "__main__":
    main()