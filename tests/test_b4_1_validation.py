import json
from datetime import datetime
from pathlib import Path

from app.models.article import AbstractSection, Article
from app.models.assessment import RankedArticle
from app.services.evidence import assess_article
from app.services.clinical_extraction import extract_clinical
from app.services.persistence import build_html_report, build_markdown_report


FIXTURE = Path(__file__).parent / "fixtures" / "b4_1_real_articles" / "visible_articles.jsonl"


def _article(record):
    return Article(
        record["pmid"],
        record["title"],
        record.get("abstract", ""),
        publication_types=tuple(record.get("publication_types", ())),
        abstract_sections=tuple(AbstractSection(s["label"], s["text"]) for s in record.get("abstract_sections", ())),
    )


def test_real_b4_1_fixture_has_twenty_source_linked_records():
    records = [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8-sig").splitlines()]
    assert len(records) == 20
    assert len({record["pmid"] for record in records}) == 20
    assert all(record["pmid"] in record["pubmed_url"] for record in records)


def test_extraction_keeps_supporting_spans_and_does_not_invent_empty_values():
    records = [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8-sig").splitlines()]
    for record in records:
        extraction = extract_clinical(_article(record))
        for provenance in extraction.population.provenance:
            assert provenance.supporting_span
            assert provenance.article_pmid == record["pmid"]
        assert extraction.pmid == record["pmid"]


def test_markdown_and_html_use_policy_cards_and_collapsed_details():
    records = [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8-sig").splitlines()[:2]]
    articles = [_article(r) for r in records]
    ranked = [RankedArticle(article, assess_article(article, datetime(2026, 8, 14), "acyclovir efficacy and safety")) for article in articles]
    markdown = build_markdown_report("acyclovir efficacy and safety", datetime(2026, 8, 14), ranked=ranked)
    html = build_html_report("acyclovir efficacy and safety", datetime(2026, 8, 14), ranked=ranked)
    assert "Clinical evidence card" in markdown
    assert "<details>" in markdown
    assert 'class="clinical-card"' in html
    assert '<details class="abstract">' in html
    assert "higher_strength" not in html
