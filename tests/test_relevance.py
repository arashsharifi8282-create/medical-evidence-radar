"""Deterministic offline acceptance tests for Phase B2."""

from datetime import date, datetime
import hashlib
import json
from pathlib import Path

from app.models.article import AbstractSection, Article, MeshDescriptor
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


def frozen_acyclovir_article(pmid: str) -> Article:
    path = Path(__file__).parent / "fixtures" / "acyclovir_b3_1" / "frozen_articles.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    raw = next(item for item in rows if item["pmid"] == pmid)
    return Article(
        pmid=raw["pmid"],
        title=raw["title"],
        abstract=raw["abstract"],
        publication_types=tuple(raw["publication_types"]),
        keywords=tuple(raw["keywords"]),
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


def test_b2_2b_intent_focus_population_section_and_audit_rules():
    safety_target = build_clinical_target(
        "losartan safety in hypertension", intervention="losartan", condition="hypertension",
        query_intents=("safety",),
    )
    safety = article("s1", "Losartan adverse-event safety in hypertension", abstract="Results: adverse events were compared.")
    efficacy_only = article("s2", "Losartan efficacy in hypertension trial", abstract="Blood pressure benefit.")
    assert assess_candidate(safety, safety_target, NOW).relevance_class == "direct"
    mismatch = assess_candidate(efficacy_only, safety_target, NOW)
    assert mismatch.relevance_class == "contextual" and mismatch.needs_review

    class_target = target()
    class_article = article("s3", "ARB safety in hypertension", abstract="Adverse events across ARB therapy.")
    assert assess_candidate(class_article, class_target, NOW).relevance_class == "class_level"

    mechanism_target = build_clinical_target("resmetirom emerging pharmacotherapy in MASLD", intervention="resmetirom", condition="MASLD", query_intents=("emerging_pharmacotherapy",))
    mechanism = article("s4", "Nitric oxide pathway in MASLD", abstract="Mechanism research trend; resmetirom is background context.")
    assessed = assess_candidate(mechanism, mechanism_target, NOW)
    assert (assessed.relevance_class, assessed.content_role) == ("contextual", "emerging_mechanism")

    enabler = article("s5", "Digital pathology AI for MASLD trials", abstract="Resmetirom is mentioned as a current option.")
    assert assess_candidate(enabler, mechanism_target, NOW).content_role == "research_enabler"

    background = article("s6", "MASLD disease management review", abstract="Background: resmetirom may be considered.")
    assert assess_candidate(background, mechanism_target, NOW).relevance_class == "contextual"

    mouse = article("s7", "Semaglutide safety in obese mice", abstract="Animal model adverse events in mice.")
    sema_target = build_clinical_target("semaglutide safety in obesity", intervention="semaglutide", condition="obesity", query_intents=("safety",))
    assert assess_candidate(mouse, sema_target, NOW).relevance_class == "irrelevant"

    structured = Article("s8", "Semaglutide safety in obesity", "Background semaglutide.", abstract_sections=(AbstractSection("BACKGROUND", "Semaglutide background."), AbstractSection("RESULTS", "Semaglutide adverse events in obesity.")))
    structured_assessment = assess_candidate(structured, sema_target, NOW)
    assert structured_assessment.relevance_class == "direct"
    assert any(s.source_field == "abstract_results" for s in structured_assessment.intervention_signals)

    snapshot = build_snapshot("topic", "topic", NOW, candidates=(AssessedCandidate(structured, structured_assessment),), clinical_target=sema_target)
    audit = snapshot["articles"][0]["clinical_relevance"]
    assert audit["needs_review"] is False and audit["content_role"] == "clinical_evidence"


def test_incidental_background_and_preclinical_queries_are_handled_conservatively():
    target_record = build_clinical_target(
        "acyclovir efficacy and safety in herpes zoster",
        intervention="acyclovir",
        condition="herpes zoster",
        intervention_labels=("acyclovir",),
        query_intents=("efficacy", "safety"),
    )
    tofacitinib = article(
        "t1",
        "Successful initial tofacitinib treatment for acute severe ulcerative colitis with steroid resistance: a case series.",
        abstract="Only one patient experienced an adverse event, local herpes zoster, and was treated with acyclovir.",
        types=("Case Reports", "Journal Article"),
    )
    genital_review = article(
        "t2",
        "Valacyclovir for the treatment of genital herpes.",
        abstract="Genital herpes is common. Herpes zoster can also be painful. Oral acyclovir and related agents are discussed.",
        types=("Review", "Journal Article"),
    )
    rat = article(
        "t3",
        "The neurological safety of intrathecal acyclovir in rats.",
        abstract="Rats received intrathecal acyclovir and neurological outcomes were assessed.",
        types=("Journal Article",),
    )
    preclinical_target = build_clinical_target(
        "acyclovir preclinical safety in rats",
        intervention="acyclovir",
        condition="rats",
        intervention_labels=("acyclovir",),
        query_intents=("safety",),
    )

    assert assess_candidate(tofacitinib, target_record, NOW).relevance_class == "contextual"
    assert assess_candidate(genital_review, target_record, NOW).relevance_class == "contextual"
    assert assess_candidate(rat, target_record, NOW).relevance_class == "irrelevant"
    assert assess_candidate(rat, preclinical_target, NOW).relevance_class == "direct"


def test_frozen_acyclovir_fixture_replays_focus_and_population_failures():
    target_record = build_clinical_target(
        "acyclovir efficacy and safety in herpes zoster",
        intervention="acyclovir",
        condition="herpes zoster",
        intervention_labels=("acyclovir",),
        query_intents=("efficacy", "safety"),
    )
    assert assess_candidate(frozen_acyclovir_article("36593812"), target_record, NOW).relevance_class == "contextual"
    assert assess_candidate(frozen_acyclovir_article("16771614"), target_record, NOW).relevance_class == "contextual"
    assert assess_candidate(frozen_acyclovir_article("34452412"), target_record, NOW).relevance_class == "contextual"
    assert assess_candidate(frozen_acyclovir_article("22270746"), target_record, NOW).relevance_class == "irrelevant"


def test_b2_2b_pilot_fixture_is_separate_preserved_and_decision_mapping_is_covered():
    path = Path(__file__).parent / "fixtures" / "relevance_b2_2b" / "batch_01_reviewer_01_responses.jsonl"
    raw = path.read_bytes()
    rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line]
    assert len(rows) == 10
    assert hashlib.sha256(raw).hexdigest() == "a70f1ce6c7dc4734a1d51150422a3658d55c5e9c4c4fed56eedff9e123dde93d"
    assert all(row["reviewer_notes"] and row["source_snapshot_sha256"] for row in rows)
    assert {row["selected_relevance_class"] for row in rows} == {"direct", "class_level", "contextual", "irrelevant"}
    assert not (Path(__file__).parent / "fixtures" / "relevance_benchmark_small" / "adjudicated_labels.jsonl").read_text(encoding="utf-8").count("B01-")


def test_b2_2b_real_frozen_snapshot_replay_reproduces_all_reviewer_classes():
    articles_path = Path(__file__).parent / "fixtures" / "relevance_b2_2b" / "real_frozen_batch_01_articles.jsonl"
    reviewer_path = Path(__file__).parent / "fixtures" / "relevance_b2_2b" / "batch_01_reviewer_01_responses.jsonl"
    reviewer = {(x["topic_id"], x["pmid"]): x for x in map(json.loads, reviewer_path.read_text(encoding="utf-8").splitlines())}
    frozen = [json.loads(line) for line in articles_path.read_text(encoding="utf-8").splitlines()]
    assert len(frozen) == len(reviewer) == 10
    actual = {}
    for row in frozen:
        raw = row["article"]
        article_record = Article(raw["pmid"], raw["title"], raw["abstract"], publication_types=tuple(raw["publication_types"]), keywords=tuple(raw["keywords"]), mesh_descriptors=tuple(MeshDescriptor(x["text"], x["ui"], x.get("major_topic", False), x.get("supporting_pmid", "")) for x in raw["mesh_descriptors"]))
        if row["topic_id"] == "losartan_hypertension":
            target_record = build_clinical_target("losartan safety in hypertension", intervention="losartan", condition="hypertension", intervention_labels=("losartan",), query_intents=("safety",))
        elif row["topic_id"] == "masld_mash_multi_intervention":
            target_record = build_clinical_target("resmetirom emerging pharmacotherapy in MASLD/MASH", intervention="resmetirom", condition="MASLD", intervention_labels=("resmetirom",), condition_labels=("MASLD", "MASH", "metabolic dysfunction-associated steatohepatitis", "fatty liver", "non-alcoholic fatty liver disease"), query_intents=("emerging_pharmacotherapy",), intervention_logic="OR", target_interventions=("resmetirom", "semaglutide", "tirzepatide", "survodutide", "efruxifermin", "pegozafermin", "lanifibranor", "denifanstat", "FGF21", "thyroid hormone receptor beta", "pan-PPAR", "de novo lipogenesis"))
        else:
            target_record = build_clinical_target("semaglutide safety in obesity", intervention="semaglutide", condition="obesity", intervention_labels=("semaglutide",), query_intents=("safety",), confirmed_classes=(ConfirmedDrugClass("glp1", "GLP-1 receptor agonists", "fixture", "has_member", "", ("GLP-1 receptor", "GLP-1 RAs", "glucagon-like peptide-1 receptor agonist")), ConfirmedDrugClass("weight-loss", "Anti-Obesity Agents", "fixture", "has_member", "", ("medications utilised for weight loss",))))
        assessment = assess_candidate(article_record, target_record, NOW)
        actual[(row["topic_id"], raw["pmid"])] = assessment
        assert row["source_snapshot_sha256"] == reviewer[(row["topic_id"], raw["pmid"])]["source_snapshot_sha256"]
        assert assessment.intervention_signals and assessment.condition_signals
    assert {key: value.relevance_class for key, value in actual.items()} == {key: value["selected_relevance_class"] for key, value in reviewer.items()}
