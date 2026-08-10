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