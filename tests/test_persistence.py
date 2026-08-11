"""Tests for local file persistence (JSON snapshot + Markdown + HTML reports)."""

import json
from datetime import date, datetime
from pathlib import Path

from app.models.article import Article
from app.services.persistence import (
    build_html_report,
    build_markdown_report,
    build_snapshot,
    save_html_report,
    save_markdown_report,
    save_snapshot,
)

FIXED_DT = datetime(2026, 8, 10, 9, 30, 0)


def _sample_articles() -> list[Article]:
    return [
        Article(
            pmid="38522001",
            title="Cardiovascular outcomes with GLP-1 receptor agonists in type 2 diabetes: a systematic review.",
            abstract="GLP-1 receptor agonists reduce major adverse cardiovascular events.",
            authors=("Smith JA", "Chen ML"),
            journal="Diabetes care",
            publication_date_raw="2024 Jun",
            publication_types=("Journal Article", "Systematic Review"),
            doi="10.2337/dc24-0123",
            pubmed_url="https://pubmed.ncbi.nlm.nih.gov/38522001/",
        ),
        Article(
            pmid="38521990",
            title="Semaglutide in patients with obesity and heart failure with preserved ejection fraction.",
            abstract="Semaglutide improved symptoms and physical function.",
            authors=("Kosiborod MN",),
            journal="The New England journal of medicine",
            publication_date_raw="2024 May 30",
            publication_types=("Journal Article", "Randomized Controlled Trial"),
            doi="10.1056/NEJMoa2403919",
            pubmed_url="https://pubmed.ncbi.nlm.nih.gov/38521990/",
        ),
    ]


def test_save_snapshot_writes_timestamped_json(tmp_path: Path):
    articles = _sample_articles()
    snapshot = build_snapshot(
        topic="GLP-1-based therapies",
        query="GLP-1-based therapies",
        fetched_at=FIXED_DT,
        articles=articles,
    )
    path = save_snapshot(snapshot, output_dir=tmp_path, fetched_at=FIXED_DT)

    assert path.exists()
    assert path.name == "pubmed_20260810_093000.json"
    assert path.parent == tmp_path

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["topic"] == "GLP-1-based therapies"
    assert data["query"] == "GLP-1-based therapies"
    assert data["fetched_at"] == "2026-08-10T09:30:00"
    assert len(data["articles"]) == 2

    first = data["articles"][0]
    assert first["pmid"] == "38522001"
    assert first["title"].startswith("Cardiovascular outcomes")
    assert first["authors"] == ["Smith JA", "Chen ML"]
    assert first["publication_types"] == ["Journal Article", "Systematic Review"]
    assert first["doi"] == "10.2337/dc24-0123"
    assert first["pubmed_url"] == "https://pubmed.ncbi.nlm.nih.gov/38522001/"
    assert first["abstract"].startswith("GLP-1 receptor agonists")


def test_save_snapshot_uses_safe_query_slug_and_collision_suffix(tmp_path: Path):
    snapshot = build_snapshot(
        topic="Topic",
        query='Psilocybin: PTSD / safety? *',
        fetched_at=FIXED_DT,
        articles=[],
    )

    first = save_snapshot(snapshot, output_dir=tmp_path, fetched_at=FIXED_DT, query=snapshot["query"])
    second = save_snapshot(snapshot, output_dir=tmp_path, fetched_at=FIXED_DT, query=snapshot["query"])

    assert first.name == "psilocybin_ptsd_safety.json"
    assert second.name == "psilocybin_ptsd_safety_20260810_093000.json"
    assert first.exists()
    assert second.exists()


def test_save_markdown_report_writes_timestamped_md(tmp_path: Path):
    articles = _sample_articles()
    markdown = build_markdown_report(
        topic="GLP-1-based therapies",
        fetched_at=FIXED_DT,
        articles=articles,
    )
    path = save_markdown_report(markdown, output_dir=tmp_path, fetched_at=FIXED_DT)

    assert path.exists()
    assert path.name == "pubmed_20260810_093000.md"
    assert path.parent == tmp_path

    text = path.read_text(encoding="utf-8")
    assert "# PubMed Report: GLP-1-based therapies" in text
    assert "**Fetch timestamp:** 2026-08-10T09:30:00" in text
    assert "Cardiovascular outcomes with GLP-1 receptor agonists" in text
    assert "**Publication date as listed by PubMed:** 2024 Jun" in text
    assert "**Publication types:** Journal Article, Systematic Review" in text
    assert "**DOI:** 10.2337/dc24-0123" in text
    assert "https://pubmed.ncbi.nlm.nih.gov/38522001/" in text
    assert "**Abstract:** GLP-1 receptor agonists reduce major adverse cardiovascular events." in text


def test_markdown_headings_are_not_escaped():
    articles = _sample_articles()
    markdown = build_markdown_report(
        topic="GLP-1-based therapies",
        fetched_at=FIXED_DT,
        articles=articles,
    )

    # Headings must be real Markdown headings, not escaped or bold text.
    assert "# PubMed Report: GLP-1-based therapies" in markdown
    assert "## 1. Cardiovascular outcomes with GLP-1 receptor agonists in type 2 diabetes: a systematic review." in markdown
    assert "## 2. Semaglutide in patients with obesity and heart failure with preserved ejection fraction." in markdown
    # No escaped heading markers.
    assert "\\# PubMed Report" not in markdown
    assert "\\#\\# 1." not in markdown
    # Headings must not be rendered as bold text containing a heading.
    assert "**# PubMed Report" not in markdown
    assert "**## 1." not in markdown


def test_markdown_bold_labels_are_not_escaped():
    articles = _sample_articles()
    markdown = build_markdown_report(
        topic="GLP-1-based therapies",
        fetched_at=FIXED_DT,
        articles=articles,
    )

    # Bold labels must be real Markdown bold, not escaped.
    assert "**Fetch timestamp:** 2026-08-10T09:30:00" in markdown
    assert "**Articles:** 2" in markdown
    assert "**Publication date as listed by PubMed:** 2024 Jun" in markdown
    assert "**Publication types:** Journal Article, Systematic Review" in markdown
    assert "**DOI:** 10.2337/dc24-0123" in markdown
    assert "**Abstract:** GLP-1 receptor agonists reduce major adverse cardiovascular events." in markdown
    # No escaped bold markers.
    assert "\\*\\*Fetch timestamp" not in markdown
    assert "\\*\\*Publication types" not in markdown
    assert "\\*\\*DOI" not in markdown


def test_markdown_separators_are_not_escaped():
    articles = _sample_articles()
    markdown = build_markdown_report(
        topic="GLP-1-based therapies",
        fetched_at=FIXED_DT,
        articles=articles,
    )

    # Separators must be plain Markdown horizontal rules, not escaped.
    assert "\n---\n" in markdown
    # No escaped separators.
    assert "\\---" not in markdown


def test_markdown_pubmed_links_are_clickable_and_not_escaped():
    articles = _sample_articles()
    markdown = build_markdown_report(
        topic="GLP-1-based therapies",
        fetched_at=FIXED_DT,
        articles=articles,
    )

    # Links must be clickable Markdown with descriptive text.
    assert "[Open in PubMed](https://pubmed.ncbi.nlm.nih.gov/38522001/)" in markdown
    assert "[Open in PubMed](https://pubmed.ncbi.nlm.nih.gov/38521990/)" in markdown
    # No escaped link syntax.
    assert "\\[Open in PubMed\\]" not in markdown
    # The URL must not be used as the link text.
    assert "[https://pubmed.ncbi.nlm.nih.gov/38522001/](https://pubmed.ncbi.nlm.nih.gov/38522001/)" not in markdown


def test_markdown_date_label_uses_raw_value_and_does_not_imply_future_publication():
    # A future journal issue date (e.g. "2026 Oct 01") must not be presented
    # as the publication date; only the raw PubMed-listed value is shown.
    articles = [
        Article(
            pmid="42348985",
            title="NLRP3 inflammasome as a central target.",
            abstract="",
            publication_date_raw="2026 Oct 01",
            publication_date=date(2026, 10, 1),
            publication_types=("Journal Article", "Review"),
            doi="10.1016/j.intimp.2026.117063",
            pubmed_url="https://pubmed.ncbi.nlm.nih.gov/42348985/",
        )
    ]
    markdown = build_markdown_report(
        topic="GLP-1-based therapies",
        fetched_at=FIXED_DT,
        articles=articles,
    )

    # The label must clarify the date is as listed by PubMed.
    assert "**Publication date as listed by PubMed:** 2026 Oct 01" in markdown
    # The raw value must be preserved exactly.
    assert "2026 Oct 01" in markdown
    # The parsed ISO date must not be shown as the publication date.
    assert "**Publication date:** 2026-10-01" not in markdown
    assert "2026-10-01" not in markdown


def test_save_html_report_writes_timestamped_html(tmp_path: Path):
    articles = _sample_articles()
    html_report = build_html_report(
        topic="GLP-1-based therapies",
        fetched_at=FIXED_DT,
        articles=articles,
    )
    path = save_html_report(html_report, output_dir=tmp_path, fetched_at=FIXED_DT)

    assert path.exists()
    assert path.name == "pubmed_20260810_093000.html"
    assert path.parent == tmp_path

    text = path.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in text
    assert '<html lang="en">' in text
    assert "<title>PubMed Report: GLP-1-based therapies</title>" in text
    assert "PubMed Report: GLP-1-based therapies" in text
    assert "2026-08-10T09:30:00" in text
    assert "Cardiovascular outcomes with GLP-1 receptor agonists" in text
    assert "Publication date:" in text
    assert "2024 Jun" in text
    assert "Publication types:" in text
    assert "Journal Article, Systematic Review" in text
    assert "DOI:" in text
    assert "10.2337/dc24-0123" in text
    assert "https://pubmed.ncbi.nlm.nih.gov/38522001/" in text
    assert "Open in PubMed" in text
    assert "Abstract:" in text
    assert "GLP-1 receptor agonists reduce major adverse cardiovascular events." in text


def test_html_report_uses_source_cards():
    articles = _sample_articles()
    html_report = build_html_report(
        topic="GLP-1-based therapies",
        fetched_at=FIXED_DT,
        articles=articles,
    )

    # Each article is rendered as a source card.
    assert html_report.count('<article class="card">') == 2
    assert "Cardiovascular outcomes with GLP-1 receptor agonists" in html_report
    assert "Semaglutide in patients with obesity and heart failure" in html_report


def test_html_report_has_header_with_topic_timestamp_and_count():
    articles = _sample_articles()
    html_report = build_html_report(
        topic="GLP-1-based therapies",
        fetched_at=FIXED_DT,
        articles=articles,
    )

    assert '<header class="report-header">' in html_report
    assert "<h1>PubMed Report: GLP-1-based therapies</h1>" in html_report
    assert "2026-08-10T09:30:00" in html_report
    assert "Articles" in html_report
    assert "2" in html_report


def test_html_report_escapes_article_content():
    articles = [
        Article(
            pmid="999",
            title="<script>alert('xss')</script> & \"quoted\" title",
            abstract="Abstract with <b>bold</b> & <i>italic</i> & \"quotes\"",
            publication_date_raw="2024 <Jun>",
            publication_types=("Type <A>", "Type & B"),
            doi="10.1/doi&x",
            pubmed_url="https://example.com/?a=1&b=2",
        )
    ]
    html_report = build_html_report(
        topic="Topic <&>",
        fetched_at=FIXED_DT,
        articles=articles,
    )

    # Raw dangerous content must not appear unescaped.
    assert "<script>alert('xss')</script>" not in html_report
    assert "<b>bold</b>" not in html_report
    assert "<i>italic</i>" not in html_report
    assert "Type <A>" not in html_report
    assert "2024 <Jun>" not in html_report

    # Escaped content must be present.
    assert "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;" in html_report
    assert "&lt;b&gt;bold&lt;/b&gt;" in html_report
    assert "&lt;i&gt;italic&lt;/i&gt;" in html_report
    assert "Type &lt;A&gt;" in html_report
    assert "2024 &lt;Jun&gt;" in html_report
    assert "Topic &lt;&amp;&gt;" in html_report


def test_html_report_has_no_external_dependencies():
    articles = _sample_articles()
    html_report = build_html_report(
        topic="GLP-1-based therapies",
        fetched_at=FIXED_DT,
        articles=articles,
    )

    # No external CDN, JavaScript, or framework references.
    # The only URLs allowed are the PubMed article links.
    assert "<script" not in html_report
    assert "cdn" not in html_report.lower()
    assert "unpkg" not in html_report.lower()
    assert "jsdelivr" not in html_report.lower()
    assert "bootstrap" not in html_report.lower()
    assert "react" not in html_report.lower()
    assert "vue" not in html_report.lower()
    assert "angular" not in html_report.lower()
    # No external stylesheet or script references.
    assert "<link" not in html_report
    assert "src=" not in html_report
    # Only pubmed.ncbi.nlm.nih.gov URLs are present.
    assert html_report.count("https://") == 2
    assert "https://pubmed.ncbi.nlm.nih.gov/38522001/" in html_report
    assert "https://pubmed.ncbi.nlm.nih.gov/38521990/" in html_report


def test_html_report_uses_inline_css():
    articles = _sample_articles()
    html_report = build_html_report(
        topic="GLP-1-based therapies",
        fetched_at=FIXED_DT,
        articles=articles,
    )

    assert "<style>" in html_report
    assert "</style>" in html_report
    assert "body {" in html_report
    assert ".card {" in html_report
    assert ".report-header {" in html_report


def test_html_report_has_clickable_pubmed_links():
    articles = _sample_articles()
    html_report = build_html_report(
        topic="GLP-1-based therapies",
        fetched_at=FIXED_DT,
        articles=articles,
    )

    assert 'href="https://pubmed.ncbi.nlm.nih.gov/38522001/"' in html_report
    assert 'href="https://pubmed.ncbi.nlm.nih.gov/38521990/"' in html_report
    assert "Open in PubMed" in html_report


def test_html_report_uses_raw_publication_date():
    articles = [
        Article(
            pmid="42348985",
            title="NLRP3 inflammasome as a central target.",
            abstract="",
            publication_date_raw="2026 Oct 01",
            publication_date=date(2026, 10, 1),
            publication_types=("Journal Article", "Review"),
            doi="10.1016/j.intimp.2026.117063",
            pubmed_url="https://pubmed.ncbi.nlm.nih.gov/42348985/",
        )
    ]
    html_report = build_html_report(
        topic="GLP-1-based therapies",
        fetched_at=FIXED_DT,
        articles=articles,
    )

    # The raw PubMed-listed date is shown, not the parsed ISO date.
    assert "2026 Oct 01" in html_report
    assert "2026-10-01" not in html_report


def test_save_creates_parent_directories(tmp_path: Path):
    articles = _sample_articles()
    snapshot = build_snapshot(
        topic="t",
        query="q",
        fetched_at=FIXED_DT,
        articles=articles,
    )
    nested = tmp_path / "a" / "b" / "c"
    path = save_snapshot(snapshot, output_dir=nested, fetched_at=FIXED_DT)
    assert path.exists()
    assert path.parent == nested


def test_timestamped_filenames_do_not_overwrite(tmp_path: Path):
    articles = _sample_articles()
    snapshot = build_snapshot(
        topic="t",
        query="q",
        fetched_at=FIXED_DT,
        articles=articles,
    )
    path1 = save_snapshot(snapshot, output_dir=tmp_path, fetched_at=FIXED_DT)
    path2 = save_snapshot(snapshot, output_dir=tmp_path, fetched_at=FIXED_DT)

    assert path1 == path2  # same timestamp -> same filename (overwrite)
    # Different timestamps produce different filenames.
    later = datetime(2026, 8, 10, 10, 0, 0)
    path3 = save_snapshot(snapshot, output_dir=tmp_path, fetched_at=later)
    assert path3.name == "pubmed_20260810_100000.json"
    assert path3 != path1