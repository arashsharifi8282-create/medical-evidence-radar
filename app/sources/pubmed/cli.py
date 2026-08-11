"""Orchestrator for the PubMed vertical slice.

Composes ESearch -> EFetch -> normalize -> rank -> expand into a single
``fetch_and_rank`` callable. ESummary is intentionally not used in this path.

With ``--save``, the fetched results are also persisted locally as a
machine-readable JSON snapshot, a human-readable Markdown report, a standalone
HTML report, and a topic profile JSON.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from app.models.article import Article
from app.models.assessment import RankedArticle
from app.models.topic_profile import TopicProfile
from app.models.concept import ConceptNormalizationResult
from app.services.concept_normalization import normalize_medical_concepts
from app.services.evidence import rank_articles
from app.services.normalizer import normalize_article, parse_pubmed_articles
from app.services.persistence import (
    DEFAULT_HTML_DIR,
    DEFAULT_JSON_DIR,
    DEFAULT_MD_DIR,
    DEFAULT_CONCEPT_DIR,
    build_html_report,
    build_markdown_report,
    build_snapshot,
    save_html_report,
    save_markdown_report,
    save_snapshot,
    save_concept_file,
    concept_path_for_topic,
)
from app.services.topic_expansion import (
    DEFAULT_PROFILE_DIR,
    build_topic_profile,
    load_topic_profile,
    merge_topic_profiles,
    profile_path_for_topic,
    save_topic_profile,
)
from app.sources.pubmed.client import PubMedClient
from app.sources.rxnorm.client import RxNormClient

DEFAULT_QUERY = "GLP-1-based therapies"
DEFAULT_RETMAX = 10


def fetch_top_recent(
    query: str = DEFAULT_QUERY,
    retmax: int = DEFAULT_RETMAX,
    client: PubMedClient | None = None,
) -> list[Article]:
    """Fetch the ``retmax`` most recent PubMed articles for ``query``.

    ``client`` is injectable for testing; defaults to a real ``PubMedClient``.
    The original free-text query is passed verbatim to PubMed's Automatic Term
    Mapping (ATM). No query modification is performed in v1.
    """
    client = client or PubMedClient()

    pmids = client.esearch(query, retmax=retmax)
    if not pmids:
        return []

    xml = client.efetch(pmids)
    return [normalize_article(elem) for elem in parse_pubmed_articles(xml)]


def save_results(
    ranked: list[RankedArticle],
    topic: str = DEFAULT_QUERY,
    query: str = DEFAULT_QUERY,
    fetched_at: datetime | None = None,
    profile: TopicProfile | None = None,
    json_dir: Path = DEFAULT_JSON_DIR,
    md_dir: Path = DEFAULT_MD_DIR,
    html_dir: Path = DEFAULT_HTML_DIR,
    profile_dir: Path = DEFAULT_PROFILE_DIR,
    concept_dir: Path = DEFAULT_CONCEPT_DIR,
    concepts: ConceptNormalizationResult | None = None,
) -> tuple[Path, Path, Path, Path]:
    """Persist ``ranked`` articles and the topic profile.

    Returns the paths of the four created files (JSON, Markdown, HTML, profile).
    """
    fetched_at = fetched_at or datetime.now()

    if profile is None:
        profile = build_topic_profile(topic, ranked, fetched_at)
    if concepts is None:
        concepts = normalize_medical_concepts(ranked, profile, rxnorm_client=None)

    snapshot = build_snapshot(
        topic=topic,
        query=query,
        fetched_at=fetched_at,
        ranked=ranked,
        profile=profile,
        concepts=concepts,
    )
    json_path = save_snapshot(snapshot, output_dir=json_dir, fetched_at=fetched_at, query=query)

    markdown = build_markdown_report(
        topic=topic,
        fetched_at=fetched_at,
        ranked=ranked,
        profile=profile,
        concepts=concepts,
    )
    md_path = save_markdown_report(markdown, output_dir=md_dir, fetched_at=fetched_at, query=query)

    html_report = build_html_report(
        topic=topic,
        fetched_at=fetched_at,
        ranked=ranked,
        profile=profile,
        concepts=concepts,
    )
    html_path = save_html_report(html_report, output_dir=html_dir, fetched_at=fetched_at, query=query)

    # Persist the topic profile (always write one, even if empty).
    profile_path = save_topic_profile(profile, output_dir=profile_dir)
    save_concept_file(topic, concepts, output_dir=concept_dir)

    return json_path, md_path, html_path, profile_path


def _load_or_new_profile(topic: str, profile_dir: Path) -> TopicProfile | None:
    """Load an existing topic profile for ``topic``, or return ``None``."""
    path = profile_path_for_topic(topic, output_dir=profile_dir)
    return load_topic_profile(path)


def main(argv: list[str] | None = None) -> None:
    """CLI entrypoint: print ranked articles for a free-text topic.

    The original free-text topic is passed verbatim to PubMed's Automatic Term
    Mapping (ATM). Discovered terms are saved/displayed but not used to alter
    retrieval in v1.

    With ``--save``, also persist a JSON snapshot, a Markdown report, an HTML
    report, and a topic profile JSON.
    """
    parser = argparse.ArgumentParser(
        prog="python -m app.sources.pubmed.cli",
        description="Fetch recent PubMed articles for a free-text topic, rank by evidence, and optionally save locally.",
    )
    parser.add_argument(
        "--topic",
        default=DEFAULT_QUERY,
        help=f"Free-text topic description (default: {DEFAULT_QUERY!r}).",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save a JSON snapshot, a Markdown report, an HTML report, and a topic profile.",
    )
    args = parser.parse_args(argv)

    topic = args.topic

    articles = fetch_top_recent(topic)
    print(f"Fetched {len(articles)} articles for query: {topic!r}\n")

    fetched_at = datetime.now()
    ranked = rank_articles(articles, fetched_at, topic)

    for r in ranked:
        article = r.article
        a = r.assessment
        print(f"PMID: {article.pmid}")
        print(f"Title: {article.title}")
        print(f"Journal: {article.journal}")
        print(f"Date (raw): {article.publication_date_raw!r} -> {article.publication_date}")
        print(f"Authors: {', '.join(article.authors)}")
        print(f"Types: {', '.join(article.publication_types)}")
        print(f"DOI: {article.doi}")
        print(f"URL: {article.pubmed_url}")
        print(f"Evidence level: {a.evidence_level_label}")
        print(f"Scores: evidence {a.evidence_score}/100, relevance {a.relevance_score}/100, overall {a.overall_score}/100")
        print(f"Section: {a.section}")
        abstract_preview = article.abstract[:200] if article.abstract else "Abstract not available in PubMed"
        print(f"Abstract: {abstract_preview}{'...' if len(article.abstract) > 200 else ''}")
        print("-" * 80)

    if args.save:
        # Build the topic profile, merging with any existing profile.
        new_profile = build_topic_profile(topic, ranked, fetched_at)
        existing_profile = _load_or_new_profile(topic, DEFAULT_PROFILE_DIR)
        merged_profile = merge_topic_profiles(existing_profile, new_profile)
        concept_result = normalize_medical_concepts(ranked, merged_profile, RxNormClient())

        json_path, md_path, html_path, profile_path = save_results(
            ranked,
            topic=topic,
            query=topic,
            fetched_at=fetched_at,
            profile=merged_profile,
            concepts=concept_result,
        )
        print(f"\nSaved JSON snapshot: {json_path}")
        print(f"Saved Markdown report: {md_path}")
        print(f"Saved HTML report: {html_path}")
        print(f"Saved topic profile: {profile_path}")
        print(f"Saved concept file: {concept_path_for_topic(topic)}")
        for warning in concept_result.warnings:
            print(f"Warning: {warning}")


if __name__ == "__main__":
    main()