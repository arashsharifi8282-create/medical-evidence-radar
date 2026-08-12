"""Deterministic offline acceptance tests for Phase B2."""

from datetime import date, datetime

from app.models.article import Article, MeshDescriptor
from app.models.relevance import AssessedCandidate, ConfirmedDrugClass
from app.models.retrieval import RetrievalBatch
from app.services.persistence import build_html_report, build_markdown_report, build_snapshot
from app.services.relevance import (
    assess_candidate,
    build_clinical_target,
    build_search_quality_summary,
    deduplicate_articles,
    rank_and_select_candidates,
)

NOW = datetime(2026, 8, 11, 9, 0)


def article(pmid: str, title: str, *, abstract: str = "", mesh=(), types=("Journal Article",)):
    return Article(
        pmid=pmid,
        title=title,
        abstract=abstract,
        publication_date=date(2026, 7, 1),
        publication_date_raw="2026 Jul",
        publication_types=types,
        mesh_descriptors=tuple(
            MeshDescriptor(text, ui, major, pmid) for text, ui, major in mesh
        ),
    )


def target(*, confirmed=True):
    classes = (
        ConfirmedDrugClass(
            class_id="N0000175514",
            preferred_label="Angiotensin II Receptor Antagonists",
            vocabulary="MED-RT",
            relationship="has_member",
            source_rxcui="52175",
            synonyms=("ARB", "angiotensin receptor blocker"),
        ),
    ) if confirmed else ()
    return build_clinical_target(
        "losartan efficacy and safety in hypertension",
        intervention="losartan",
        condition="hypertension",
        intervention_rxcuis=("52175",),
        intervention_labels=("losartan",),
        confirmed_classes=classes,
        candidate_articles=(),
    )


def test_direct_class_contextual_and_irrelevant_classifications():
    direct = article(
        "1", "Losartan for hypertension: a randomized controlled trial",
        mesh=(("Losartan", "D019808", True), ("Hypertension", "D006973", True)),
        types=("Randomized Controlled Trial",),
    )
    class_level = article(
        "2", "ARB therapy for hypertension",
        mesh=(("Hypertension", "D006973", True),),
    )
    contextual = article(
        "3", "Atenolol for hypertension",
        mesh=(("Atenolol", "D001262", True), ("Hypertension", "D006973", True)),
    )
    irrelevant = article(
        "39369055", "Losartan treatment in ovarian cancer",
        mesh=(("Losartan", "D019808", True), ("Ovarian Neoplasms", "D010051", True)),
    )

    assert assess_candidate(direct, target(), NOW).relevance_class == "direct"
    assert assess_candidate(class_level, target(), NOW).relevance_class == "class_level"
    assert assess_candidate(class_level, target(confirmed=False), NOW).relevance_class == "contextual"
    assert assess_candidate(contextual, target(), NOW).relevance_class == "contextual"
    excluded = assess_candidate(irrelevant, target(), NOW)
    assert excluded.relevance_class == "irrelevant"
    assert excluded.decision == "excluded_irrelevant"
    assert "Ovarian Neoplasms" in excluded.reason


def test_relevance_precedes_evidence_ranking_and_irrelevant_never_reaches_key_evidence():
    direct = article(
        "1", "Losartan for hypertension randomized trial",
        types=("Randomized Controlled Trial",),
    )
    class_review = article(
        "2", "ARB for hypertension systematic review",
        types=("Systematic Review", "Meta-Analysis"),
    )
    contextual_review = article(
        "3", "Atenolol for hypertension systematic review",
        types=("Systematic Review", "Meta-Analysis"),
    )
    ovarian = article(
        "39369055", "Losartan systematic review in ovarian cancer",
        types=("Systematic Review", "Meta-Analysis"),
    )
    assessed = [
        AssessedCandidate(item, assess_candidate(item, target(), NOW))
        for item in (contextual_review, class_review, ovarian, direct)
    ]
    selected, audited, _ = rank_and_select_candidates(
        assessed, NOW, "losartan efficacy and safety in hypertension", 10
    )

    assert [item.article.pmid for item in selected] == ["1", "2", "3"]
    markdown = build_markdown_report(
        "losartan efficacy and safety in hypertension", NOW, selected
    )
    key_evidence = markdown.split("## Class-level evidence", 1)[0]
    assert "Losartan for hypertension randomized trial" in key_evidence
    assert "ovarian cancer" not in markdown.casefold()
    assert next(item for item in audited if item.article.pmid == "39369055").relevance.decision == "excluded_irrelevant"


def test_snapshot_retains_all_decisions_signals_reasons_and_quality_counts():
    direct = article("1", "Losartan for hypertension")
    irrelevant = article("39369055", "Losartan for ovarian cancer")
    assessed = [
        AssessedCandidate(item, assess_candidate(item, target(), NOW))
        for item in (direct, irrelevant)
    ]
    selected, audited, _ = rank_and_select_candidates(
        assessed, NOW, "losartan efficacy and safety in hypertension", 1
    )
    batch = RetrievalBatch(
        "losartan efficacy and safety in hypertension", 50, 127, (direct, irrelevant)
    )
    quality = build_search_quality_summary(batch, audited, 1)
    snapshot = build_snapshot(
        topic=batch.query,
        query=batch.query,
        fetched_at=NOW,
        ranked=selected,
        candidates=tuple(audited),
        clinical_target=target(),
        search_quality=quality,
    )

    assert snapshot["search_quality"]["candidate_limit"] == 50
    assert snapshot["search_quality"]["report_limit"] == 1
    assert len(snapshot["articles"]) == 2
    excluded = next(item for item in snapshot["articles"] if item["pmid"] == "39369055")
    audit = excluded["clinical_relevance"]
    assert audit["decision"] == "excluded_irrelevant"
    assert audit["reason"]
    assert audit["assessed_at"] == NOW.isoformat()
    assert audit["matched_intervention_signals"][0]["source_field"] == "title"


def test_deduplication_empty_fewer_than_limit_and_collapsed_html_background():
    direct = article("1", "Losartan for hypertension")
    contextual = article("2", "Atenolol for hypertension")
    unique, duplicates = deduplicate_articles([direct, direct, contextual])
    assert [item.pmid for item in unique] == ["1", "2"]
    assert duplicates == ("1",)

    assert rank_and_select_candidates([], NOW, "topic", 10) == ([], [], [])
    candidates = [
        AssessedCandidate(item, assess_candidate(item, target(), NOW))
        for item in unique
    ]
    selected, audited, _ = rank_and_select_candidates(candidates, NOW, "topic", 10)
    assert len(selected) == 2
    assert all(item.relevance.decision.startswith("included_") for item in audited)
    html = build_html_report("topic", NOW, selected)
    assert '<details class="report-section contextual-evidence"' in html