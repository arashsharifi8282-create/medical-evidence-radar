"""Map raw PubMed EFetch XML into normalized :class:`Article` records.

This module is pure: it performs no I/O. It parses XML already fetched by the
client and returns :class:`Article` dataclasses.
"""

from __future__ import annotations

import calendar
import xml.etree.ElementTree as ET
from datetime import date

from app.models.article import Article

# Month name -> number, used to resolve PubMed's abbreviated month names.
_MONTHS = {name.lower(): num for num, name in enumerate(calendar.month_name) if name}
_MONTHS.update({abbr.lower(): num for num, abbr in enumerate(calendar.month_abbr) if abbr})

_PUBMED_BASE_URL = "https://pubmed.ncbi.nlm.nih.gov"


def parse_pubmed_articles(xml_text: str) -> list[ET.Element]:
    """Parse an EFetch XML document and return the list of ``<PubmedArticle>`` elements."""
    root = ET.fromstring(xml_text)
    if root.tag == "PubmedArticle":
        return [root]
    return root.findall(".//PubmedArticle")


def normalize_article(article_elem: ET.Element) -> Article:
    """Convert a single ``<PubmedArticle>`` element into an :class:`Article`."""
    pmid = _text(article_elem, ".//PMID") or ""
    title = _text(article_elem, ".//ArticleTitle") or ""
    abstract = _abstract(article_elem)
    authors = _authors(article_elem)
    journal = _text(article_elem, ".//Journal/Title") or ""
    publication_date_raw, publication_date = _publication_date(article_elem)
    electronic_publication_date = _electronic_publication_date(article_elem)
    is_epub_ahead_of_print = electronic_publication_date is not None and publication_date is None
    publication_types = _publication_types(article_elem)
    doi = _doi(article_elem)
    pubmed_url = f"{_PUBMED_BASE_URL}/{pmid}/" if pmid else ""
    mesh_headings = _mesh_headings(article_elem)
    keywords = _keywords(article_elem)

    return Article(
        pmid=pmid,
        title=title,
        abstract=abstract,
        authors=authors,
        journal=journal,
        publication_date=publication_date,
        publication_date_raw=publication_date_raw,
        electronic_publication_date=electronic_publication_date,
        is_epub_ahead_of_print=is_epub_ahead_of_print,
        publication_types=publication_types,
        doi=doi,
        pubmed_url=pubmed_url,
        mesh_headings=mesh_headings,
        keywords=keywords,
    )


def _text(elem: ET.Element, path: str) -> str | None:
    """Return the text of the first element matching ``path``, or ``None``."""
    found = elem.find(path)
    return found.text if found is not None and found.text else None


def _abstract(article_elem: ET.Element) -> str:
    """Concatenate all ``<AbstractText>`` segments into a single string."""
    segments = [
        seg.text.strip()
        for seg in article_elem.findall(".//Abstract/AbstractText")
        if seg.text and seg.text.strip()
    ]
    return " ".join(segments)


def _authors(article_elem: ET.Element) -> tuple[str, ...]:
    """Extract author names, handling both individual and collective authors."""
    names: list[str] = []
    for author in article_elem.findall(".//AuthorList/Author"):
        collective = _text(author, "CollectiveName")
        if collective:
            names.append(collective)
            continue
        last = _text(author, "LastName") or ""
        initials = _text(author, "Initials") or ""
        if last:
            names.append(f"{last} {initials}".strip())
    return tuple(names)


def _publication_types(article_elem: ET.Element) -> tuple[str, ...]:
    """Extract publication type labels."""
    return tuple(
        pt.text.strip()
        for pt in article_elem.findall(".//PublicationTypeList/PublicationType")
        if pt.text and pt.text.strip()
    )


def _doi(article_elem: ET.Element) -> str:
    """Extract the DOI from ``<ArticleId IdType="doi">``."""
    for article_id in article_elem.findall(".//ArticleIdList/ArticleId"):
        if article_id.get("IdType") == "doi" and article_id.text:
            return article_id.text.strip()
    return ""


def _mesh_headings(article_elem: ET.Element) -> tuple[str, ...]:
    """Extract MeSH descriptor names from ``<MeshHeadingList>``."""
    return tuple(
        dh.text.strip()
        for dh in article_elem.findall(".//MeshHeadingList/MeshHeading/DescriptorName")
        if dh.text and dh.text.strip()
    )


def _keywords(article_elem: ET.Element) -> tuple[str, ...]:
    """Extract author keywords from ``<KeywordList>``."""
    return tuple(
        kw.text.strip()
        for kw in article_elem.findall(".//KeywordList/Keyword")
        if kw.text and kw.text.strip()
    )


def _publication_date(article_elem: ET.Element) -> tuple[str, date | None]:
    """Extract the raw publication date text and a precise :class:`date`.

    Rules:
    - Always preserve the raw date text in ``publication_date_raw``.
    - Return a ``date`` only when a precise ISO date can be determined:
      * Year + Month + Day -> ``date(year, month, day)``
      * Year + Month       -> ``date(year, month, 1)``
    - Return ``None`` for year-only, season-only, or ambiguous ranges
      (e.g. ``2024 Mar-Apr``, ``2024 Spring``). Never invent a day or month.
    """
    pub_date = article_elem.find(".//JournalIssue/PubDate")
    if pub_date is None:
        return "", None

    year = _text(pub_date, "Year")
    month = _text(pub_date, "Month")
    day = _text(pub_date, "Day")
    medline_date = _text(pub_date, "MedlineDate")

    raw = _raw_date_text(pub_date, year, month, day, medline_date)

    if year and month and day:
        month_num = _month_number(month)
        if month_num is not None:
            try:
                return raw, date(int(year), month_num, int(day))
            except ValueError:
                return raw, None
        return raw, None

    if year and month:
        month_num = _month_number(month)
        if month_num is not None:
            try:
                return raw, date(int(year), month_num, 1)
            except ValueError:
                return raw, None

    # Year-only, season-only, MedlineDate, or ambiguous -> no precise date.
    return raw, None


def _electronic_publication_date(article_elem: ET.Element) -> date | None:
    """Extract the electronic publication date from ``<ArticleDate DateType="Electronic">``."""
    for article_date in article_elem.findall(".//ArticleDate"):
        if article_date.get("DateType") != "Electronic":
            continue
        year = _text(article_date, "Year")
        month = _text(article_date, "Month")
        day = _text(article_date, "Day")
        if year and month and day:
            month_num = _month_number(month)
            if month_num is not None:
                try:
                    return date(int(year), month_num, int(day))
                except ValueError:
                    return None
    return None


def _raw_date_text(
    pub_date: ET.Element,
    year: str | None,
    month: str | None,
    day: str | None,
    medline_date: str | None,
) -> str:
    """Build the raw date string exactly as PubMed presented it."""
    if medline_date:
        return medline_date.strip()
    parts = [p for p in (year, month, day) if p]
    return " ".join(parts).strip()


def _month_number(month: str) -> int | None:
    """Resolve a month name/abbreviation to its number, or ``None`` if unknown."""
    value = month.strip()
    if value.isdigit():
        number = int(value)
        return number if 1 <= number <= 12 else None
    return _MONTHS.get(value.lower())