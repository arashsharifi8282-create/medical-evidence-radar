"""Local file persistence for fetched PubMed results.

This module is pure: it takes ranked :class:`RankedArticle` records plus metadata
and writes machine-readable JSON snapshots, human-readable Markdown reports,
and standalone HTML reports to timestamped files. No network calls are made here.
"""

from __future__ import annotations

import html
import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path

from app.models.article import Article
from app.models.assessment import RankedArticle
from app.models.concept import ArticleConceptLink, ConceptNormalizationResult, NormalizedConcept
from app.services.evidence import assess_article
from app.models.topic_profile import CandidateTerm, TopicProfile

DEFAULT_JSON_DIR = Path("data/raw/pubmed")
DEFAULT_MD_DIR = Path("reports/pubmed")
DEFAULT_HTML_DIR = Path("reports/pubmed")
DEFAULT_CONCEPT_DIR = Path("data/concepts")


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
        "electronic_publication_date": (
            article.electronic_publication_date.isoformat()
            if article.electronic_publication_date
            else None
        ),
        "is_epub_ahead_of_print": article.is_epub_ahead_of_print,
        "publication_types": list(article.publication_types),
        "doi": article.doi,
        "pubmed_url": article.pubmed_url,
        "source": article.source,
        "mesh_headings": list(article.mesh_headings),
        "mesh_descriptors": [
            {
                "text": descriptor.text,
                "ui": descriptor.ui,
                "major_topic": descriptor.major_topic,
                "supporting_pmid": descriptor.supporting_pmid,
            }
            for descriptor in article.mesh_descriptors
        ],
        "keywords": list(article.keywords),
    }


def _assessment_to_dict(assessment) -> dict:
    """Convert an :class:`EvidenceAssessment` into a JSON-serializable dict."""
    return {
        "evidence_level": assessment.evidence_level,
        "evidence_level_label": assessment.evidence_level_label,
        "relevance_score": assessment.relevance_score,
        "evidence_score": assessment.evidence_score,
        "overall_score": assessment.overall_score,
        "is_future_issue_dated": assessment.is_future_issue_dated,
        "is_electronic_only": assessment.is_electronic_only,
        "has_abstract": assessment.has_abstract,
        "abstract_status": assessment.abstract_status,
        "reasons": list(assessment.reasons),
        "limitations": list(assessment.limitations),
        "section": assessment.section,
    }


def _candidate_to_dict(c: CandidateTerm) -> dict:
    return {
        "term": c.term,
        "source": c.source,
        "document_frequency": c.document_frequency,
        "evidence_max": c.evidence_max,
        "recency_days": c.recency_days,
        "direct_topic_overlap": c.direct_topic_overlap,
        "supporting_articles": list(c.supporting_articles),
        "score": c.score,
        "reasons": list(c.reasons),
        "accepted": c.accepted,
    }


def _ranked_to_dict(r: RankedArticle) -> dict:
    """Convert a :class:`RankedArticle` into a JSON-serializable dict."""
    d = _article_to_dict(r.article)
    d["assessment"] = _assessment_to_dict(r.assessment)
    return d


def _concept_to_dict(concept: NormalizedConcept) -> dict:
    return {
        "concept_id": concept.concept_id,
        "vocabulary": concept.vocabulary,
        "preferred_label": concept.preferred_label,
        "original_term": concept.original_term,
        "concept_type": concept.concept_type,
        "match_method": concept.match_method,
        "confidence": concept.confidence,
        "supporting_pmids": list(concept.supporting_pmids),
        "source_fields": list(concept.source_fields),
    }


def _concept_link_to_dict(link: ArticleConceptLink) -> dict:
    return {
        "relationship": link.relationship,
        "pmid": link.pmid,
        "concept_id": link.concept_id,
        "source_field": link.source_field,
        "match_method": link.match_method,
        "confidence": link.confidence,
        "evidence_level": link.evidence_level,
    }


def build_snapshot(
    topic: str,
    query: str,
    fetched_at: datetime,
    ranked: list[RankedArticle] | None = None,
    profile: TopicProfile | None = None,
    concepts: ConceptNormalizationResult | None = None,
    articles: list[Article] | None = None,
) -> dict:
    """Build the JSON snapshot payload."""
    if ranked is None:
        ranked = [RankedArticle(a, assess_article(a, fetched_at, topic)) for a in (articles or [])]
    snapshot = {
        "topic": topic,
        "query": query,
        "fetched_at": fetched_at.isoformat(),
        "articles": [_ranked_to_dict(r) for r in ranked],
    }
    snapshot["discovered_terms"] = {
        "accepted": [_candidate_to_dict(c) for c in profile.accepted_terms] if profile else [],
        "rejected": [_candidate_to_dict(c) for c in profile.rejected_terms] if profile else [],
    }
    snapshot["normalized_concepts"] = [
        _concept_to_dict(concept) for concept in concepts.normalized_concepts
    ] if concepts else []
    snapshot["article_concept_links"] = [
        _concept_link_to_dict(link) for link in concepts.article_concept_links
    ] if concepts else []
    snapshot["concept_normalization_warnings"] = list(concepts.warnings) if concepts else []
    return snapshot


def _normalized_concepts_markdown(concepts: ConceptNormalizationResult | None) -> str:
    """Build an explainable concept section without clinical interpretation."""
    if concepts is None:
        return ""
    lines = ["## Normalized medical concepts", ""]
    for warning in concepts.warnings:
        lines.append(f"> **Warning:** {warning}")
        lines.append("")
    if not concepts.normalized_concepts:
        lines.extend(["No medical concepts were normalized.", ""])
        return "\n".join(lines)
    for concept in concepts.normalized_concepts:
        pmids = ", ".join(concept.supporting_pmids) or "none"
        lines.extend(
            [
                f"- **{concept.preferred_label}**",
                f"  - Concept ID: `{concept.concept_id}`",
                f"  - Vocabulary: {concept.vocabulary}",
                f"  - Original term: {concept.original_term}",
                f"  - Confidence: {concept.confidence:.2f}",
                f"  - Supporting PMIDs: {pmids}",
                f"  - Match method: {concept.match_method}",
                "",
            ]
        )
    return "\n".join(lines)


def _discovered_terms_markdown(profile: TopicProfile | None) -> str:
    """Build the 'Discovered terms' Markdown section."""
    if profile is None:
        return ""
    lines: list[str] = []
    lines.append("## Discovered terms")
    lines.append("")
    if not profile.accepted_terms and not profile.rejected_terms:
        lines.append("No candidate terms were discovered from MeSH headings or author keywords.")
        lines.append("")
        return "\n".join(lines)

    if profile.accepted_terms:
        lines.append("### Accepted")
        lines.append("")
        for c in profile.accepted_terms:
            lines.append(f"- **{c.term}** — accepted (score {c.score:.0f}/100, DF {c.document_frequency}, evidence {c.evidence_max}, source {c.source})")
            for reason in c.reasons:
                lines.append(f"  - Why: {reason}")
            lines.append("")
    if profile.rejected_terms:
        lines.append("### Rejected")
        lines.append("")
        for c in profile.rejected_terms:
            lines.append(f"- **{c.term}** — rejected (score {c.score:.0f}/100, DF {c.document_frequency}, evidence {c.evidence_max}, source {c.source})")
            for reason in c.reasons:
                lines.append(f"  - Why: {reason}")
            lines.append("")
    return "\n".join(lines)


def build_markdown_report(
    topic: str,
    fetched_at: datetime,
    ranked: list[RankedArticle] | None = None,
    profile: TopicProfile | None = None,
    concepts: ConceptNormalizationResult | None = None,
    articles: list[Article] | None = None,
) -> str:
    """Build a human-readable Markdown report."""
    legacy_articles = ranked is None and articles is not None
    if ranked is None:
        ranked = [RankedArticle(a, assess_article(a, fetched_at, topic)) for a in (articles or [])]
    lines: list[str] = []
    lines.append(f"# PubMed Report: {topic}")
    lines.append("")
    lines.append(f"**Fetch timestamp:** {fetched_at.isoformat()}")
    lines.append("")
    lines.append(f"**Articles:** {len(ranked)}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Discovered terms section.
    discovered = _discovered_terms_markdown(profile)
    if discovered:
        lines.append(discovered)
        lines.append("---")
        lines.append("")

    normalized = _normalized_concepts_markdown(concepts)
    if normalized:
        lines.append(normalized)
        lines.append("---")
        lines.append("")

    # Preserve the original article-only API as a flat report for callers that
    # have not opted into Phase-A sectioned ranking.
    if legacy_articles:
        for i, r in enumerate(ranked, start=1):
            article = r.article
            a = r.assessment
            lines.append(f"## {i}. {article.title}")
            lines.append("")
            lines.append(f"- **Publication date as listed by PubMed:** {article.publication_date_raw}")
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

    # Group by section.
    sections = {
        "key_evidence": "Key evidence",
        "important_updates": "Important updates",
        "exploratory_evidence": "Exploratory evidence",
    }
    for section_key, section_label in sections.items():
        section_articles = [r for r in ranked if r.assessment.section == section_key]
        if not section_articles:
            continue
        lines.append(f"## {section_label}")
        lines.append("")

        for i, r in enumerate(section_articles, start=1):
            article = r.article
            a = r.assessment
            lines.append(f"## {i}. {article.title}")
            lines.append("")
            lines.append(f"- **Evidence level:** {a.evidence_level_label}")
            lines.append(f"- **Evidence score:** {a.evidence_score}/100")
            lines.append(f"- **Relevance score:** {a.relevance_score}/100")
            lines.append(f"- **Overall score:** {a.overall_score}/100")
            if article.publication_date_raw:
                lines.append(
                    f"- **Publication date as listed by PubMed:** {article.publication_date_raw}"
                )
            if article.electronic_publication_date:
                lines.append(
                    f"- **Electronic publication date:** {article.electronic_publication_date.isoformat()}"
                )
            if a.is_future_issue_dated:
                lines.append("- **Status:** Future journal-issue date (scheduled, not yet published)")
            if a.is_electronic_only:
                lines.append("- **Status:** Available electronically ahead of print")
            if article.publication_types:
                lines.append(f"- **Publication types:** {', '.join(article.publication_types)}")
            if article.doi:
                lines.append(f"- **DOI:** {article.doi}")
            if article.pubmed_url:
                lines.append(f"- **PubMed:** [Open in PubMed]({article.pubmed_url})")
            if a.reasons:
                lines.append(f"- **Why included:** {'; '.join(a.reasons)}")
            if a.limitations:
                lines.append(f"- **Limitations:** {'; '.join(a.limitations)}")
            if article.abstract:
                lines.append("")
                lines.append(f"**Abstract:** {article.abstract}")
            else:
                lines.append("")
                lines.append("**Abstract:** Abstract not available in PubMed")
            lines.append("")
            lines.append("---")
            lines.append("")

    return "\n".join(lines)


def _discovered_terms_html(profile: TopicProfile | None) -> str:
    """Build the 'Discovered terms' HTML section."""
    if profile is None:
        return ""
    e = html.escape
    parts: list[str] = ['<section class="discovered-terms">', '<h2>Discovered terms</h2>']

    if not profile.accepted_terms and not profile.rejected_terms:
        parts.append(
            '<p class="discovered-empty">No candidate terms were discovered from '
            "MeSH headings or author keywords.</p>"
        )
    else:
        if profile.accepted_terms:
            parts.append('<h3>Accepted</h3>')
            parts.append('<ul class="term-list">')
            for c in profile.accepted_terms:
                reasons_html = "".join(
                    f'<li class="term-reason">{e(reason)}</li>' for reason in c.reasons
                )
                parts.append(
                    f'<li class="term-item term-accepted">'
                    f'<span class="term-name">{e(c.term)}</span> '
                    f'<span class="term-badge accepted">accepted</span> '
                    f'<span class="term-meta">score {c.score:.0f}/100 · DF {c.document_frequency} · '
                    f'evidence {e(c.evidence_max)} · source {e(c.source)}</span>'
                    f'<ul class="term-reasons">{reasons_html}</ul>'
                    f"</li>"
                )
            parts.append("</ul>")
        if profile.rejected_terms:
            parts.append("<h3>Rejected</h3>")
            parts.append('<ul class="term-list">')
            for c in profile.rejected_terms:
                reasons_html = "".join(
                    f'<li class="term-reason">{e(reason)}</li>' for reason in c.reasons
                )
                parts.append(
                    f'<li class="term-item term-rejected">'
                    f'<span class="term-name">{e(c.term)}</span> '
                    f'<span class="term-badge rejected">rejected</span> '
                    f'<span class="term-meta">score {c.score:.0f}/100 · DF {c.document_frequency} · '
                    f'evidence {e(c.evidence_max)} · source {e(c.source)}</span>'
                    f'<ul class="term-reasons">{reasons_html}</ul>'
                    f"</li>"
                )
            parts.append("</ul>")

    parts.append("</section>")
    return "\n".join(parts)


def _normalized_concepts_html(concepts: ConceptNormalizationResult | None) -> str:
    if concepts is None:
        return ""
    e = html.escape
    parts = ['<section class="normalized-concepts">', "<h2>Normalized medical concepts</h2>"]
    for warning in concepts.warnings:
        parts.append(f'<p class="concept-warning"><strong>Warning:</strong> {e(warning)}</p>')
    if not concepts.normalized_concepts:
        parts.append('<p class="concept-empty">No medical concepts were normalized.</p>')
    else:
        parts.append('<ul class="concept-list">')
        for concept in concepts.normalized_concepts:
            pmids = ", ".join(concept.supporting_pmids) or "none"
            parts.append(
                '<li class="concept-item">'
                f'<span class="concept-name">{e(concept.preferred_label)}</span>'
                f'<dl><dt>Concept ID</dt><dd>{e(concept.concept_id)}</dd>'
                f'<dt>Vocabulary</dt><dd>{e(concept.vocabulary)}</dd>'
                f'<dt>Original term</dt><dd>{e(concept.original_term)}</dd>'
                f'<dt>Confidence</dt><dd>{concept.confidence:.2f}</dd>'
                f'<dt>Supporting PMIDs</dt><dd>{e(pmids)}</dd>'
                f'<dt>Match method</dt><dd>{e(concept.match_method)}</dd></dl>'
                "</li>"
            )
        parts.append("</ul>")
    parts.append("</section>")
    return "\n".join(parts)


def build_html_report(
    topic: str,
    fetched_at: datetime,
    ranked: list[RankedArticle] | None = None,
    profile: TopicProfile | None = None,
    concepts: ConceptNormalizationResult | None = None,
    articles: list[Article] | None = None,
) -> str:
    """Build a polished, standalone HTML report directly from ranked data.

    All article content is escaped with :func:`html.escape`. The page uses
    inline CSS only — no external CDN, JavaScript, or frameworks.
    """
    if ranked is None:
        ranked = [RankedArticle(a, assess_article(a, fetched_at, topic)) for a in (articles or [])]
    e = html.escape
    esc_topic = e(topic)
    esc_fetched_at = e(fetched_at.isoformat())
    article_count = len(ranked)

    # Group by section.
    sections = {
        "key_evidence": "Key evidence",
        "important_updates": "Important updates",
        "exploratory_evidence": "Exploratory evidence",
    }

    section_html_parts: list[str] = []
    for section_key, section_label in sections.items():
        section_articles = [r for r in ranked if r.assessment.section == section_key]
        if not section_articles:
            continue

        cards: list[str] = []
        for i, r in enumerate(section_articles, start=1):
            article = r.article
            a = r.assessment

            esc_title = e(article.title)
            esc_date_raw = e(article.publication_date_raw)
            esc_types = e(", ".join(article.publication_types))
            esc_doi = e(article.doi)
            esc_url = e(article.pubmed_url)
            esc_abstract = e(article.abstract)
            esc_epub_date = (
                e(article.electronic_publication_date.isoformat())
                if article.electronic_publication_date
                else ""
            )

            meta_items: list[str] = []
            meta_items.append(
                f'<div class="meta-item"><span class="meta-label">Evidence level:</span> '
                f'<span class="meta-value">{e(a.evidence_level_label)}</span></div>'
            )
            meta_items.append(
                f'<div class="meta-item"><span class="meta-label">Evidence score:</span> '
                f'<span class="meta-value">{a.evidence_score}/100</span></div>'
            )
            meta_items.append(
                f'<div class="meta-item"><span class="meta-label">Relevance score:</span> '
                f'<span class="meta-value">{a.relevance_score}/100</span></div>'
            )
            meta_items.append(
                f'<div class="meta-item"><span class="meta-label">Overall score:</span> '
                f'<span class="meta-value">{a.overall_score}/100</span></div>'
            )
            if esc_date_raw:
                meta_items.append(
                    f'<div class="meta-item"><span class="meta-label">Publication date:</span> '
                    f'<span class="meta-value">{esc_date_raw}</span></div>'
                )
            if esc_epub_date:
                meta_items.append(
                    f'<div class="meta-item"><span class="meta-label">Electronic publication date:</span> '
                    f'<span class="meta-value">{esc_epub_date}</span></div>'
                )
            if a.is_future_issue_dated:
                meta_items.append(
                    '<div class="meta-item"><span class="meta-label">Status:</span> '
                    '<span class="meta-value status-future">Future journal-issue date '
                    "(scheduled, not yet published)</span></div>"
                )
            if a.is_electronic_only:
                meta_items.append(
                    '<div class="meta-item"><span class="meta-label">Status:</span> '
                    '<span class="meta-value status-epub">Available electronically ahead of print</span></div>'
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
            if a.reasons:
                reasons_html = "".join(
                    f'<li class="reason-item">{e(reason)}</li>' for reason in a.reasons
                )
                meta_items.append(
                    f'<div class="meta-item"><span class="meta-label">Why included:</span> '
                    f'<ul class="reason-list">{reasons_html}</ul></div>'
                )
            if a.limitations:
                limitations_html = "".join(
                    f'<li class="limitation-item">{e(lim)}</li>' for lim in a.limitations
                )
                meta_items.append(
                    f'<div class="meta-item"><span class="meta-label">Limitations:</span> '
                    f'<ul class="limitation-list">{limitations_html}</ul></div>'
                )

            if esc_abstract:
                abstract_html = (
                    f'<div class="abstract"><span class="abstract-label">Abstract:</span> '
                    f'<p class="abstract-text">{esc_abstract}</p></div>'
                )
            else:
                abstract_html = (
                    '<div class="abstract abstract-missing">'
                    '<span class="abstract-label">Abstract:</span> '
                    '<p class="abstract-text">Abstract not available in PubMed</p>'
                    "</div>"
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

        section_html_parts.append(
            f'<section class="report-section" id="{section_key}">'
            f'<h2 class="section-heading">{e(section_label)}</h2>'
            f'{"".join(cards)}'
            f"</section>"
        )

    cards_html = "\n".join(section_html_parts)
    discovered_html = _discovered_terms_html(profile)
    concepts_html = _normalized_concepts_html(concepts)

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

    .report-section {{
      margin-bottom: 2.5rem;
    }}

    .section-heading {{
      font-size: 1.4rem;
      font-weight: 700;
      color: #1a365d;
      margin-bottom: 1rem;
      padding-bottom: 0.5rem;
      border-bottom: 2px solid #e2e8f0;
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

    .status-future {{
      color: #c05621;
      font-weight: 600;
    }}

    .status-epub {{
      color: #2b6cb0;
      font-weight: 600;
    }}

    .reason-list, .limitation-list {{
      margin: 0.25rem 0 0 1.25rem;
      padding: 0;
    }}

    .reason-item, .limitation-item {{
      font-size: 0.88rem;
      color: #4a5568;
    }}

    .abstract {{
      background-color: #f7fafc;
      border-left: 4px solid #2b6cb0;
      border-radius: 0 6px 6px 0;
      padding: 1rem 1.25rem;
    }}

    .abstract-missing {{
      border-left-color: #a0aec0;
      background-color: #f7fafc;
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

    .discovered-terms {{
      background: #ffffff;
      border: 1px solid #e2e8f0;
      border-radius: 10px;
      padding: 1.75rem 2rem;
      margin-bottom: 2rem;
      box-shadow: 0 2px 6px rgba(0, 0, 0, 0.06);
    }}

    .discovered-terms h2 {{
      font-size: 1.3rem;
      font-weight: 700;
      color: #1a365d;
      margin-bottom: 1rem;
    }}

    .discovered-terms h3 {{
      font-size: 1.05rem;
      font-weight: 600;
      color: #2d3748;
      margin: 1rem 0 0.5rem;
    }}

    .term-list {{
      list-style: none;
      padding: 0;
      margin: 0;
    }}

    .term-item {{
      padding: 0.5rem 0;
      border-bottom: 1px solid #edf2f7;
    }}

    .term-item:last-child {{
      border-bottom: none;
    }}

    .term-name {{
      font-weight: 600;
      color: #2d3748;
    }}

    .term-badge {{
      display: inline-block;
      font-size: 0.75rem;
      font-weight: 600;
      padding: 0.1rem 0.5rem;
      border-radius: 9999px;
      margin-left: 0.5rem;
    }}

    .term-badge.accepted {{
      background-color: #c6f6d5;
      color: #22543d;
    }}

    .term-badge.rejected {{
      background-color: #fed7d7;
      color: #742a2a;
    }}

    .term-meta {{
      font-size: 0.85rem;
      color: #718096;
      margin-left: 0.5rem;
    }}

    .term-reasons {{
      margin: 0.25rem 0 0 1.25rem;
      padding: 0;
    }}

    .term-reason {{
      font-size: 0.85rem;
      color: #4a5568;
    }}

    .discovered-empty {{
      color: #718096;
      font-size: 0.95rem;
    }}

    .normalized-concepts {{
      background: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px;
      padding: 1.75rem 2rem; margin-bottom: 2rem;
      box-shadow: 0 2px 6px rgba(0, 0, 0, 0.06);
    }}
    .normalized-concepts h2 {{ color: #1a365d; margin-bottom: 1rem; }}
    .concept-list {{ list-style: none; }}
    .concept-item {{ padding: 0.75rem 0; border-bottom: 1px solid #edf2f7; }}
    .concept-name {{ font-weight: 700; color: #2d3748; }}
    .concept-item dl {{ display: grid; grid-template-columns: 10rem 1fr; gap: 0.2rem 1rem; }}
    .concept-item dt {{ font-weight: 600; color: #4a5568; }}
    .concept-warning {{ color: #9c4221; margin-bottom: 0.75rem; }}

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

    {discovered_html}

    {concepts_html}

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


def _query_slug(query: str) -> str:
    """Create a readable, filesystem-safe filename stem from a user query.

    Unicode letters (including Persian text) are retained. Windows-reserved
    filename characters and punctuation are replaced/removed, and an empty
    result falls back to ``query``.
    """
    normalized = unicodedata.normalize("NFKC", query).strip().lower()
    normalized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", normalized)
    normalized = re.sub(r"[^\w\s-]", "", normalized, flags=re.UNICODE)
    slug = re.sub(r"[\s_-]+", "_", normalized).strip("._-")
    if not slug or slug.upper() in {"CON", "PRN", "AUX", "NUL"}:
        return "query"
    return slug


def _path_for_output(
    output_dir: Path,
    extension: str,
    fetched_at: datetime,
    query: str | None,
) -> Path:
    """Return a query-named path, adding a timestamp only on collision."""
    if query is None:
        return output_dir / f"pubmed_{_timestamp_str(fetched_at)}.{extension}"

    base = output_dir / f"{_query_slug(query)}.{extension}"
    if not base.exists():
        return base
    return output_dir / f"{_query_slug(query)}_{_timestamp_str(fetched_at)}.{extension}"


def save_snapshot(
    snapshot: dict,
    output_dir: Path = DEFAULT_JSON_DIR,
    fetched_at: datetime | None = None,
    query: str | None = None,
) -> Path:
    """Write the JSON snapshot to a query-named file and return its path."""
    fetched_at = fetched_at or datetime.now()
    output_dir.mkdir(parents=True, exist_ok=True)
    path = _path_for_output(output_dir, "json", fetched_at, query)
    path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def save_markdown_report(
    markdown: str,
    output_dir: Path = DEFAULT_MD_DIR,
    fetched_at: datetime | None = None,
    query: str | None = None,
) -> Path:
    """Write the Markdown report to a query-named file and return its path."""
    fetched_at = fetched_at or datetime.now()
    output_dir.mkdir(parents=True, exist_ok=True)
    path = _path_for_output(output_dir, "md", fetched_at, query)
    path.write_text(markdown, encoding="utf-8")
    return path


def save_html_report(
    html_report: str,
    output_dir: Path = DEFAULT_HTML_DIR,
    fetched_at: datetime | None = None,
    query: str | None = None,
) -> Path:
    """Write the HTML report to a query-named file and return its path."""
    fetched_at = fetched_at or datetime.now()
    output_dir.mkdir(parents=True, exist_ok=True)
    path = _path_for_output(output_dir, "html", fetched_at, query)
    path.write_text(html_report, encoding="utf-8")
    return path


def concept_path_for_topic(topic: str, output_dir: Path = DEFAULT_CONCEPT_DIR) -> Path:
    return output_dir / f"{_query_slug(topic)}.json"


def save_concept_file(
    topic: str,
    concepts: ConceptNormalizationResult,
    output_dir: Path = DEFAULT_CONCEPT_DIR,
) -> Path:
    """Save the latest per-topic Phase B1 concept artifact."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = concept_path_for_topic(topic, output_dir)
    payload = {
        "topic": topic,
        "normalized_concepts": [_concept_to_dict(item) for item in concepts.normalized_concepts],
        "article_concept_links": [_concept_link_to_dict(item) for item in concepts.article_concept_links],
        "warnings": list(concepts.warnings),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path