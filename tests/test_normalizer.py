"""Unit tests for the PubMed XML normalizer (no network)."""

from datetime import date
from pathlib import Path

import pytest

from app.services.normalizer import normalize_article, parse_pubmed_articles

FIXTURES = Path(__file__).parent / "fixtures"
EFETCH_XML = (FIXTURES / "efetch_sample.xml").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def articles():
    elements = parse_pubmed_articles(EFETCH_XML)
    return [normalize_article(elem) for elem in elements]


def test_parse_pubmed_articles_returns_three(articles):
    assert len(articles) == 3


def test_full_article_fields(articles):
    article = articles[0]
    assert article.pmid == "38522001"
    assert article.title == (
        "Cardiovascular outcomes with GLP-1 receptor agonists in type 2 "
        "diabetes: a systematic review."
    )
    assert article.abstract == (
        "GLP-1 receptor agonists reduce major adverse cardiovascular events in "
        "patients with type 2 diabetes. We performed a systematic review of "
        "randomized controlled trials. Across 12 trials, the pooled hazard "
        "ratio was 0.86. GLP-1 receptor agonists confer significant "
        "cardiovascular benefit."
    )
    assert article.authors == ("Smith JA", "Chen ML", "Garcia R")
    assert article.journal == "Diabetes care"
    assert article.publication_types == ("Journal Article", "Systematic Review")
    assert article.doi == "10.2337/dc24-0123"
    assert article.pubmed_url == "https://pubmed.ncbi.nlm.nih.gov/38522001/"
    assert article.source == "pubmed"


def test_mesh_headings_extracted(articles):
    article = articles[0]
    assert "Diabetes Mellitus, Type 2" in article.mesh_headings
    assert "Glucagon-Like Peptide-1 Receptor Agonists" in article.mesh_headings
    assert "Cardiovascular Diseases" in article.mesh_headings

    article = articles[1]
    assert "Heart Failure" in article.mesh_headings
    assert "Obesity" in article.mesh_headings
    assert "Glucagon-Like Peptide-1 Receptor Agonists" in article.mesh_headings

    article = articles[2]
    assert "Obesity" in article.mesh_headings
    assert "Glucagon-Like Peptide-1 Receptor Agonists" in article.mesh_headings


def test_author_keywords_extracted(articles):
    article = articles[0]
    assert "GLP-1 receptor agonists" in article.keywords
    assert "type 2 diabetes" in article.keywords
    assert "cardiovascular outcomes" in article.keywords

    article = articles[1]
    assert "semaglutide" in article.keywords
    assert "heart failure" in article.keywords

    article = articles[2]
    assert "liraglutide" in article.keywords
    assert "weight management" in article.keywords


def test_electronic_publication_date_extracted(articles):
    # Article 0 has ArticleDate DateType="Electronic": 2024-05-28.
    assert articles[0].electronic_publication_date == date(2024, 5, 28)
    # Article 1 has ArticleDate DateType="Electronic": 2024-05-14.
    assert articles[1].electronic_publication_date == date(2024, 5, 14)
    # Article 2 has no ArticleDate.
    assert articles[2].electronic_publication_date is None


def test_is_epub_ahead_of_print_flag(articles):
    # Articles 0 and 1 have both print and electronic dates -> not epub-only.
    assert articles[0].is_epub_ahead_of_print is False
    assert articles[1].is_epub_ahead_of_print is False
    # Article 2 has neither -> not epub-only.
    assert articles[2].is_epub_ahead_of_print is False


def test_month_only_date_defaults_to_first_of_month(articles):
    # PubDate: 2024 Jun (no day) -> date(2024, 6, 1)
    article = articles[0]
    assert article.publication_date_raw == "2024 Jun"
    assert article.publication_date == date(2024, 6, 1)


def test_full_date_is_preserved(articles):
    # PubDate: 2024 May 30 -> date(2024, 5, 30)
    article = articles[1]
    assert article.publication_date_raw == "2024 May 30"
    assert article.publication_date == date(2024, 5, 30)


def test_collective_author_and_missing_doi(articles):
    article = articles[2]
    assert article.authors == ("Liraglutide Study Group",)
    assert article.doi == ""
    assert article.publication_date_raw == "2024 May"
    assert article.publication_date == date(2024, 5, 1)


def test_year_only_date_is_none():
    xml = """
    <PubmedArticle>
      <MedlineCitation>
        <PMID>1</PMID>
        <Article>
          <Journal>
            <JournalIssue>
              <PubDate><Year>2024</Year></PubDate>
            </JournalIssue>
            <Title>Test journal</Title>
          </Journal>
          <ArticleTitle>Year only title</ArticleTitle>
        </Article>
      </MedlineCitation>
    </PubmedArticle>
    """
    article = normalize_article(parse_pubmed_articles(xml)[0])
    assert article.publication_date_raw == "2024"
    assert article.publication_date is None


def test_ambiguous_medline_date_is_none():
    xml = """
    <PubmedArticle>
      <MedlineCitation>
        <PMID>2</PMID>
        <Article>
          <Journal>
            <JournalIssue>
              <PubDate><MedlineDate>2024 Mar-Apr</MedlineDate></PubDate>
            </JournalIssue>
            <Title>Test journal</Title>
          </Journal>
          <ArticleTitle>Ambiguous date title</ArticleTitle>
        </Article>
      </MedlineCitation>
    </PubmedArticle>
    """
    article = normalize_article(parse_pubmed_articles(xml)[0])
    assert article.publication_date_raw == "2024 Mar-Apr"
    assert article.publication_date is None


def test_missing_pubdate_is_none():
    xml = """
    <PubmedArticle>
      <MedlineCitation>
        <PMID>3</PMID>
        <Article>
          <Journal>
            <JournalIssue/>
            <Title>Test journal</Title>
          </Journal>
          <ArticleTitle>No date title</ArticleTitle>
        </Article>
      </MedlineCitation>
    </PubmedArticle>
    """
    article = normalize_article(parse_pubmed_articles(xml)[0])
    assert article.publication_date_raw == ""
    assert article.publication_date is None


def test_epub_only_article_is_flagged():
    # Electronic date present but no print PubDate -> is_epub_ahead_of_print=True.
    xml = """
    <PubmedArticle>
      <MedlineCitation>
        <PMID>99</PMID>
        <Article>
          <Journal>
            <JournalIssue CitedMedium="Internet">
              <PubDate>
                <Year>2026</Year>
                <Month>Jul</Month>
              </PubDate>
            </JournalIssue>
            <Title>Epub ahead of print journal</Title>
          </Journal>
          <ArticleTitle>Epub only article</ArticleTitle>
          <ArticleDate DateType="Electronic">
            <Year>2026</Year>
            <Month>06</Month>
            <Day>15</Day>
          </ArticleDate>
        </Article>
      </MedlineCitation>
    </PubmedArticle>
    """
    article = normalize_article(parse_pubmed_articles(xml)[0])
    assert article.electronic_publication_date == date(2026, 6, 15)
    assert article.publication_date == date(2026, 7, 1)  # print date exists
    assert article.is_epub_ahead_of_print is False  # both dates present -> not epub-only