"""Orchestrator for the PubMed vertical slice.

Composes ESearch -> EFetch -> normalize -> rank -> expand into a single
``fetch_and_rank`` callable. ESummary is intentionally not used in this path.

With ``--save``, the fetched results are also persisted locally as a
machine-readable JSON snapshot, a human-readable Markdown report, a standalone
HTML report, and a topic profile JSON.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from app.models.article import Article
from app.models.assessment import RankedArticle
from app.models.topic_profile import TopicProfile
from app.models.concept import ConceptNormalizationResult
from app.models.relevance import (
    AssessedCandidate,
    ClinicalTarget,
    RelevanceRun,
    SearchQualitySummary,
)
from app.models.retrieval import RetrievalBatch
from app.services.concept_normalization import normalize_medical_concepts
from app.services.evidence import rank_articles
from app.services.normalizer import normalize_article, parse_pubmed_articles
from app.services.relevance import (
    assess_candidates,
    build_clinical_target,
    build_search_quality_summary,
    deduplicate_articles,
    parse_clinical_target,
    rank_and_select_candidates,
)
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
DEFAULT_CANDIDATE_LIMIT = 50
DEFAULT_REPORT_LIMIT = 10


def _console_print(value: str, *, stream=None) -> None:
    """Print safely when the active console cannot encode retrieved Unicode."""
    stream = stream or sys.stdout
    try:
        print(value, file=stream)
    except UnicodeEncodeError:
        encoding = getattr(stream, "encoding", None) or "utf-8"
        fallback = value.encode(encoding, errors="backslashreplace").decode(encoding)
        print(fallback, file=stream)


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


def fetch_recent_candidates(
    query: str = DEFAULT_QUERY,
    candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
    client: PubMedClient | None = None,
) -> RetrievalBatch:
    """Fetch and de-duplicate a recent candidate pool while retaining counts."""
    client = client or PubMedClient()
    search_result = client.search(query, retmax=candidate_limit)
    if not search_result.pmids:
        return RetrievalBatch(query, candidate_limit, search_result.total_count, ())

    xml = client.efetch(list(search_result.pmids))
    parsed = [normalize_article(elem) for elem in parse_pubmed_articles(xml)]
    # EFetch usually preserves request order; explicitly restore it so PubMed's
    # pub-date ordering remains the stable retrieval order.
    order = {pmid: index for index, pmid in enumerate(search_result.pmids)}
    parsed.sort(key=lambda article: order.get(article.pmid, len(order)))
    unique, duplicate_pmids = deduplicate_articles(parsed)
    return RetrievalBatch(
        query=query,
        candidate_limit=candidate_limit,
        total_count=search_result.total_count,
        articles=unique,
        duplicate_pmids=duplicate_pmids,
    )


def run_relevance_pipeline(
    topic: str,
    *,
    intervention: str | None = None,
    condition: str | None = None,
    candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
    report_limit: int = DEFAULT_REPORT_LIMIT,
    fetched_at: datetime | None = None,
    pubmed_client: PubMedClient | None = None,
    rxnorm_client: RxNormClient | None = None,
) -> RelevanceRun:
    """Run Phase B2 before the existing Phase-A evidence ranker."""
    fetched_at = fetched_at or datetime.now()
    batch = fetch_recent_candidates(topic, candidate_limit, pubmed_client)
    intervention_term, _, _, parse_warnings = parse_clinical_target(
        topic, intervention, condition
    )

    target_warnings = list(parse_warnings)
    rx_matches = ()
    confirmed_classes = []
    if intervention_term:
        client = rxnorm_client or RxNormClient()
        try:
            rx_matches = client.lookup(intervention_term)
            for match in rx_matches:
                confirmed_classes.extend(client.classes_for_rxcui(match.rxcui))
        except Exception as exc:
            target_warnings.append(
                f"Target RxNorm/RxClass lookup failed for {intervention_term!r}: {exc}"
            )

    target = build_clinical_target(
        topic,
        intervention=intervention,
        condition=condition,
        intervention_rxcuis=tuple(match.rxcui for match in rx_matches),
        intervention_labels=tuple(match.name for match in rx_matches),
        confirmed_classes=tuple(confirmed_classes),
        candidate_articles=batch.articles,
        warnings=tuple(target_warnings),
    )
    candidates = assess_candidates(batch.articles, target, fetched_at)
    selected, audited, all_ranked = rank_and_select_candidates(
        candidates, fetched_at, topic, report_limit
    )
    profile_ranked = tuple(
        item
        for item in all_ranked
        if item.clinical_relevance
        and item.clinical_relevance.relevance_class in ("direct", "class_level")
    )
    quality = build_search_quality_summary(batch, audited, report_limit)
    return RelevanceRun(
        retrieval=batch,
        target=target,
        candidates=tuple(audited),
        ranked=tuple(selected),
        profile_ranked=profile_ranked,
        search_quality=quality,
    )


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
    candidates: tuple[AssessedCandidate, ...] | None = None,
    clinical_target: ClinicalTarget | None = None,
    search_quality: SearchQualitySummary | None = None,
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
        candidates=candidates,
        clinical_target=clinical_target,
        search_quality=search_quality,
    )
    json_path = save_snapshot(snapshot, output_dir=json_dir, fetched_at=fetched_at, query=query)

    markdown = build_markdown_report(
        topic=topic,
        fetched_at=fetched_at,
        ranked=ranked,
        profile=profile,
        concepts=concepts,
        search_quality=search_quality,
    )
    md_path = save_markdown_report(markdown, output_dir=md_dir, fetched_at=fetched_at, query=query)

    html_report = build_html_report(
        topic=topic,
        fetched_at=fetched_at,
        ranked=ranked,
        profile=profile,
        concepts=concepts,
        search_quality=search_quality,
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
    parser.add_argument(
        "--intervention",
        help="Explicit target intervention/drug (recommended when --topic is ambiguous).",
    )
    parser.add_argument(
        "--condition",
        help="Explicit target condition (recommended when --topic is ambiguous).",
    )
    parser.add_argument(
        "--candidate-limit",
        type=_positive_int,
        default=DEFAULT_CANDIDATE_LIMIT,
        help=f"Recent PubMed candidates to assess (default: {DEFAULT_CANDIDATE_LIMIT}).",
    )
    parser.add_argument(
        "--report-limit",
        type=_positive_int,
        default=DEFAULT_REPORT_LIMIT,
        help=f"Maximum articles in the visible report (default: {DEFAULT_REPORT_LIMIT}).",
    )
    args = parser.parse_args(argv)
    emit = _console_print

    topic = args.topic

    fetched_at = datetime.now()
    rxnorm_client = RxNormClient()
    run = run_relevance_pipeline(
        topic,
        intervention=args.intervention,
        condition=args.condition,
        candidate_limit=args.candidate_limit,
        report_limit=args.report_limit,
        fetched_at=fetched_at,
        rxnorm_client=rxnorm_client,
    )
    ranked = list(run.ranked)
    quality = run.search_quality
    total = quality.total_result_count if quality.total_result_count is not None else "unknown"
    emit(f"PubMed results: {total}; fetched unique candidates: {quality.fetched_candidate_count}")
    emit(
        f"Included: {quality.included_count}; excluded: {quality.excluded_count}; "
        f"direct/class/contextual/irrelevant: {quality.direct_count}/"
        f"{quality.class_level_count}/{quality.contextual_count}/{quality.irrelevant_count}\n"
    )

    for r in ranked:
        article = r.article
        a = r.assessment
        relevance = r.clinical_relevance
        emit(f"PMID: {article.pmid}")
        emit(f"Title: {article.title}")
        emit(f"Journal: {article.journal}")
        emit(f"Date (raw): {article.publication_date_raw!r} -> {article.publication_date}")
        emit(f"Authors: {', '.join(article.authors)}")
        emit(f"Types: {', '.join(article.publication_types)}")
        emit(f"DOI: {article.doi}")
        emit(f"URL: {article.pubmed_url}")
        emit(f"Evidence level: {a.evidence_level_label}")
        if a.study_assessment:
            emit(f"Study design: {a.study_assessment.design_subtype}")
            emit(f"Evidence strength: {a.study_assessment.evidence_tier}")
            emit(f"Population scope: {a.study_assessment.population_scope}")
            emit(f"Sample size: {a.study_assessment.sample_size if a.study_assessment.sample_size is not None else 'Not reported'}")
            emit(f"Needs review: {'yes' if a.study_assessment.needs_review else 'no'}")
        if relevance:
            emit(
                f"Clinical relevance: {relevance.relevance_class} "
                f"({relevance.relevance_score}/100)"
            )
            emit(f"Why: {relevance.reason}")
        emit(f"Scores: evidence {a.evidence_score}/100, relevance {a.relevance_score}/100, overall {a.overall_score}/100")
        emit(f"Section: {a.section}")
        abstract_preview = article.abstract[:200] if article.abstract else "Abstract not available in PubMed"
        emit(f"Abstract: {abstract_preview}{'...' if len(article.abstract) > 200 else ''}")
        emit("-" * 80)

    if args.save:
        # Build the topic profile, merging with any existing profile.
        new_profile = build_topic_profile(topic, list(run.profile_ranked), fetched_at)
        existing_profile = _load_or_new_profile(topic, DEFAULT_PROFILE_DIR)
        merged_profile = merge_topic_profiles(existing_profile, new_profile)
        concept_result = normalize_medical_concepts(
            list(run.profile_ranked), merged_profile, rxnorm_client
        )

        json_path, md_path, html_path, profile_path = save_results(
            ranked,
            topic=topic,
            query=topic,
            fetched_at=fetched_at,
            profile=merged_profile,
            concepts=concept_result,
            candidates=run.candidates,
            clinical_target=run.target,
            search_quality=run.search_quality,
        )
        emit(f"\nSaved JSON snapshot: {json_path}")
        emit(f"Saved Markdown report: {md_path}")
        emit(f"Saved HTML report: {html_path}")
        emit(f"Saved topic profile: {profile_path}")
        emit(f"Saved concept file: {concept_path_for_topic(topic)}")
        for warning in concept_result.warnings:
            emit(f"Warning: {warning}")
        for warning in run.target.warnings:
            emit(f"Warning: {warning}")


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be at least 1")
    return parsed


if __name__ == "__main__":
    main()
