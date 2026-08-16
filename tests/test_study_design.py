"""Offline regression coverage for Phase B3 study-design triage."""

from datetime import datetime
import json
from pathlib import Path

from app.models.article import AbstractSection, Article
from app.services.evidence import assess_article, rank_articles
from app.services.study_design import assess_study_design


def article(*, title="Study", abstract="", types=("Journal Article",), sections=()):
    return Article(
        pmid="b3-test",
        title=title,
        abstract=abstract,
        publication_types=types,
        abstract_sections=tuple(AbstractSection(label, text) for label, text in sections),
    )


def frozen_article(pmid: str) -> Article:
    path = Path(__file__).parent / "fixtures" / "acyclovir_b3_1" / "frozen_articles.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    row = next(item for item in rows if item["pmid"] == pmid)
    return Article(
        pmid=row["pmid"],
        title=row["title"],
        abstract=row["abstract"],
        publication_types=tuple(row["publication_types"]),
        keywords=tuple(row["keywords"]),
    )


def test_systematic_meta_analysis_is_higher_strength():
    result = assess_study_design(article(
        title="Systematic review and meta-analysis",
        abstract="METHODS: Databases were searched. RESULTS: Ten studies were included.",
        types=("Journal Article", "Systematic Review", "Meta-Analysis"),
        sections=(("METHODS", "Databases were searched."), ("RESULTS", "Ten studies were included.")),
    ))
    assert result.design_family == "systematic_review_meta_analysis"
    assert result.evidence_tier == "higher_strength"
    assert result.result_status == "reported"


def test_systematic_review_without_meta_analysis_is_distinct():
    result = assess_study_design(article(
        title="Systematic review",
        abstract="METHODS: We searched databases. RESULTS: Studies were summarized.",
        types=("Journal Article", "Systematic Review"),
    ))
    assert result.design_family == "systematic_review_without_meta_analysis"
    assert result.evidence_tier == "moderate_strength"


def test_completed_rct_and_protocol_are_distinct():
    completed = assess_study_design(article(
        title="A randomized controlled trial",
        abstract="METHODS: Patients were randomized. RESULTS: Outcomes were compared.",
        types=("Randomized Controlled Trial", "Journal Article"),
    ))
    protocol = assess_study_design(article(
        title="Trial protocol",
        abstract="METHODS: The protocol describes planned enrollment.",
        types=("Journal Article", "Protocol"),
    ))
    assert completed.design_family == "randomized_controlled_trial"
    assert completed.evidence_tier == "higher_strength"
    assert protocol.design_family == "protocol"
    assert protocol.evidence_tier == "not_assessable"


def test_design_signal_precedence_keeps_weak_review_phrase_from_overriding_rct_metadata():
    result = assess_study_design(article(
        title="Randomized trial of treatment",
        abstract="This trial was compared with a previous systematic review.",
        types=("Randomized Controlled Trial",),
    ))
    assert result.design_family == "randomized_controlled_trial"
    assert any(span.source_type == "abstract" and "systematic review" in span.text.casefold() for span in result.supporting_spans)
    assert not any(span.source_type == "publication_type" and "systematic review" in span.text.casefold() for span in result.supporting_spans)


def test_credible_incompatible_design_metadata_requires_review_with_provenance():
    result = assess_study_design(article(
        title="Conflicting record",
        abstract="METHODS: Patients were evaluated.",
        types=("Randomized Controlled Trial", "Systematic Review"),
    ))
    assert result.design_family == "unknown"
    assert result.needs_review is True
    assert "conflicting_design_signals" in result.limitation_codes
    assert any("conflict" in reason.casefold() for reason in result.assessment_reasons)
    assert {span.text for span in result.supporting_spans if span.source_type == "publication_type"} >= {"Randomized Controlled Trial", "Systematic Review"}


def test_design_signal_policy_is_stable_and_allows_compatible_reinforcement():
    record = article(
        title="Randomized trial",
        abstract="METHODS: Patients were randomized in a trial.",
        types=("Randomized Controlled Trial",),
    )
    first = assess_study_design(record)
    second = assess_study_design(record)
    assert first.design_family == "randomized_controlled_trial"
    assert first.matched_signals == second.matched_signals
    assert first.supporting_spans == second.supporting_spans
    assert first.assessment_reasons == second.assessment_reasons


def test_observational_taxonomy_and_boolean_unknowns():
    result = assess_study_design(article(
        title="Retrospective cohort study",
        abstract="METHODS: Medical records were reviewed. RESULTS: Patients were followed.",
        types=("Journal Article", "Cohort Studies"),
    ))
    assert result.design_family == "retrospective_cohort"
    assert result.retrospective == "true"
    assert result.randomized == "unknown"
    assert "retrospective_design" in result.limitation_codes


def test_case_control_cross_sectional_and_diagnostic_designs():
    for types, expected in (
        (("Case-Control Studies",), "case_control"),
        (("Cross-Sectional Studies",), "cross_sectional"),
    ):
        assert assess_study_design(article(types=types, abstract="RESULTS: Associations were estimated.")).design_family == expected
    assert assess_study_design(article(title="Diagnostic accuracy study", abstract="RESULTS: Sensitivity was estimated.")).design_family == "diagnostic_accuracy"


def test_case_report_and_case_series_are_limited():
    report = assess_study_design(article(title="A case report", abstract="A patient was described.", types=("Case Reports",)))
    series = assess_study_design(article(title="A case series", abstract="Six patients were described.", types=("Case Series",)))
    assert report.design_family == "case_report"
    assert series.design_family == "case_series"
    assert report.evidence_tier == series.evidence_tier == "limited_strength"


def test_pharmacovigilance_is_signal_only_without_incidence_or_causality():
    result = assess_study_design(article(
        title="FAERS disproportionality analysis",
        abstract="METHODS: FAERS spontaneous reports were analyzed. RESULTS: Reporting odds ratios were estimated.",
    ))
    assert result.design_family == "pharmacovigilance_disproportionality"
    assert result.evidence_tier == "signal_only"
    assert {"pharmacovigilance_reporting_bias", "pharmacovigilance_no_incidence", "pharmacovigilance_no_causality"}.issubset(result.limitation_codes)
    assert result.data_source_type == "FAERS"


def test_preclinical_and_mixed_scope_are_not_human_by_default():
    animal = assess_study_design(article(title="Mice model", abstract="Mice received treatment for 3 weeks."))
    mixed = assess_study_design(article(title="Translational study", abstract="Patients and mice were studied in parallel."))
    in_vitro = assess_study_design(article(title="Cell line study", abstract="In vitro cell line experiments were performed."))
    assert animal.population_scope == "preclinical_only"
    assert animal.evidence_tier == "preclinical"
    assert mixed.population_scope == "mixed"
    assert mixed.design_family == "mixed_human_preclinical"
    assert in_vitro.design_family == "in_vitro"


def test_population_taxonomy_is_word_boundary_aware_and_mixed_when_supported():
    mice = assess_study_design(article(abstract="Mice received treatment."))
    preclinical = assess_study_design(article(abstract="Preclinical experiments were conducted."))
    clinical = assess_study_design(article(abstract="Clinical evaluation was conducted."))
    mixed_mice = assess_study_design(article(abstract="Patients and mice were evaluated in parallel."))
    mixed_preclinical = assess_study_design(article(abstract="Patients and preclinical experiments were evaluated in parallel."))
    incidental = assess_study_design(article(abstract="The clinical protocol was discussed."))
    substring = assess_study_design(article(abstract="Microclinical samples were evaluated."))
    background = assess_study_design(article(abstract="Patients were evaluated. Preclinical background was discussed."))
    assert mice.population_scope == "preclinical_only"
    assert preclinical.population_scope == "preclinical_only"
    assert clinical.population_scope == "unclear"
    assert mixed_mice.population_scope == "mixed"
    assert mixed_mice.design_family == "mixed_human_preclinical"
    assert mixed_preclinical.population_scope == "mixed"
    assert incidental.population_scope == "unclear"
    assert substring.population_scope == "unclear"
    assert background.population_scope == "human"


def test_narrative_editorial_and_unknown_are_not_overstated():
    narrative = assess_study_design(article(title="Narrative review", abstract="A narrative review of mechanisms.", types=("Review",)))
    editorial = assess_study_design(article(title="Commentary", abstract="Perspective on the field.", types=("Editorial",)))
    unknown = assess_study_design(article(title="A topic", abstract=""))
    assert narrative.evidence_tier == "limited_strength"
    assert editorial.design_family == "editorial_commentary_letter"
    assert editorial.evidence_tier == "not_assessable"
    assert unknown.design_family == "unknown"
    assert unknown.needs_review is True


def test_sample_size_extraction_rejects_dates_and_multiple_populations():
    valid = assess_study_design(article(abstract="RESULTS: 16 patients were included."))
    ambiguous = assess_study_design(article(abstract="RESULTS: 19 studies included 31 cases and 103 individuals."))
    dates = assess_study_design(article(abstract="The 2026 study followed patients for 12 weeks."))
    assert valid.sample_size == 16
    assert valid.sample_size_status == "reported"
    assert ambiguous.sample_size is None
    assert ambiguous.sample_size_status == "ambiguous"
    assert dates.sample_size is None
    assert dates.follow_up_text is not None


def test_sample_size_requires_participant_semantics_not_numeric_labels():
    for text in (
        "Arm 1 patients received treatment.",
        "The 2024 patients registry was searched.",
        "Patients received 10 mg daily.",
        "Patients were treated for 12 weeks.",
        "A response rate of 25% was observed in patients.",
        "Trial registration NCT01234567 included patients.",
        "Ten centers enrolled patients.",
        "Group 2 patients received usual care.",
        "Site 3 patients received usual care.",
    ):
        result = assess_study_design(article(abstract=text))
        assert result.sample_size is None
        assert result.sample_size_status == "not_reported"


def test_comparator_follow_up_and_data_source_are_preserved():
    result = assess_study_design(article(
        abstract="METHODS: Patients were compared with placebo for 12 weeks using an EHR database.",
    ))
    assert result.comparator_status == "reported"
    assert "placebo" in result.comparator_text.casefold()
    assert result.treatment_duration_text is not None
    assert result.follow_up_text is None
    assert result.data_source_type == "EHR"


def test_comparator_and_follow_up_require_clinical_context():
    for text in (
        "Results were compared with previous reports.",
        "Results were compared with prior studies.",
        "Results were compared with published data.",
        "Drug A and drug B were mentioned in previous reports.",
    ):
        result = assess_study_design(article(abstract=text))
        assert result.comparator_status == "not_reported"
    for text in (
        "The dose schedule allowed up to 24 weeks.",
        "Participants aged up to 24 years were eligible.",
        "Enrollment occurred up to 24 weeks after referral.",
        "Records from up to 24 years were reviewed.",
        "Up to 24 weeks were available.",
    ):
        result = assess_study_design(article(abstract=text))
        assert result.follow_up_text is None


def test_focused_taxonomy_categories_have_structured_or_narrow_signals():
    cases = (
        (article(types=("Scoping Review",)), "scoping_review", "publication_type"),
        (article(types=("Practice Guideline",)), "guideline_or_consensus", "publication_type"),
        (article(types=("Diagnostic Accuracy",)), "diagnostic_accuracy", "publication_type"),
        (article(title="Pharmacokinetic study", abstract="PK sampling was performed."), "pharmacokinetic_pharmacodynamic", "title"),
        (article(abstract="A nonrandomized intervention was evaluated."), "nonrandomized_interventional_study", "abstract"),
    )
    for record, expected, source in cases:
        result = assess_study_design(record)
        assert result.design_family == expected
        assert any(span.source_type == source for span in result.supporting_spans)
    assert assess_study_design(article(title="Scoping of a review process")).design_family != "scoping_review"
    assert assess_study_design(article(title="Pharmacokinetically guided discussion")).design_family != "pharmacokinetic_pharmacodynamic"


def test_real_world_acyclovir_sample_sizes_and_duration_are_extracted():
    enrolled = assess_study_design(article(
        title="Randomized clinical trial of famciclovir or acyclovir for the treatment of herpes zoster in adults.",
        abstract="One hundred and seventy-four patients were enrolled and randomized; 151 of these patients completed treatment.",
        types=("Journal Article", "Randomized Controlled Trial"),
    ))
    randomized = assess_study_design(article(
        abstract="A total of 87 patients were randomized to treatment.",
        types=("Randomized Controlled Trial",),
    ))
    participants = assess_study_design(article(
        abstract="This cohort included 120 participants with acute herpes zoster.",
    ))
    meta = assess_study_design(article(
        title="Network meta-analysis of antiviral agents",
        abstract="A total of 17 randomized control trials with 5,579 participants were included in this study.",
        types=("Systematic Review", "Network Meta-Analysis", "Journal Article"),
    ))
    large_rct = assess_study_design(article(
        title="Improved therapy study",
        abstract="A randomized, double-blind study in 1,227 immunocompetent patients with herpes zoster treated for 7 days and assessed up to 24 weeks.",
        types=("Journal Article",),
    ))
    pk = assess_study_design(article(
        abstract="A total of 37 immunocompromised children were enrolled on one of two studies. Pharmacokinetic data are available for 32 patients.",
        types=("Journal Article",),
    ))

    assert enrolled.sample_size == 174
    assert randomized.sample_size == 87
    assert participants.sample_size == 120
    assert meta.design_family == "systematic_review_meta_analysis"
    assert meta.sample_size == 5579
    assert large_rct.sample_size == 1227
    assert "7 days" in (large_rct.treatment_duration_text or "")
    assert "24 weeks" in (large_rct.follow_up_text or "")
    assert pk.sample_size == 37
    assert any(span.source_type == "pk_data" and "32 patients" in span.text for span in pk.supporting_spans)


def test_human_rct_with_in_vitro_background_remains_human():
    result = assess_study_design(article(
        title="Randomized trial in patients with herpes zoster",
        abstract="Patients were randomized to treatment for 7 days. In conclusion, the greater in vitro antiviral activity may explain the findings.",
        types=("Randomized Controlled Trial",),
    ))
    assert result.design_family == "randomized_controlled_trial"
    assert result.population_scope == "human"
    assert result.evidence_tier == "higher_strength"


def test_frozen_acyclovir_fixture_replays_key_study_design_failures():
    network = assess_study_design(frozen_article("37535772"))
    famciclovir = assess_study_design(frozen_article("29746903"))
    pk = assess_study_design(frozen_article("18561175"))
    brivudin = assess_study_design(frozen_article("12834860"))
    rat = assess_study_design(frozen_article("22270746"))

    assert network.design_family == "systematic_review_meta_analysis"
    assert network.sample_size == 5579
    assert famciclovir.sample_size == 174
    assert famciclovir.treatment_duration_text and "7 days" in famciclovir.treatment_duration_text
    assert pk.sample_size == 37
    assert any(span.source_type == "pk_data" for span in pk.supporting_spans)
    assert brivudin.sample_size == 1227
    assert brivudin.population_scope == "human"
    assert rat.population_scope == "preclinical_only"


def test_structured_abstract_sections_drive_results_and_provenance():
    result = assess_study_design(article(
        abstract="",
        sections=(("METHODS", "Patients were enrolled."), ("RESULTS", "8 patients were included.")),
    ))
    assert result.result_status == "reported"
    assert any(span.field == "abstract" for span in result.supporting_spans)
    assert result.sample_size == 8


def test_missing_fields_remain_not_reported_or_unknown():
    result = assess_study_design(article(title="Sparse metadata", abstract="A study was described."))
    assert result.sample_size_status == "not_reported"
    assert result.comparator_status == "not_reported"
    assert result.randomized == "unknown"
    assert result.blinded == "unknown"
    assert "sample_size_not_reported" in result.limitation_codes


def test_b3_assessment_is_serialized_and_old_level_is_preserved():
    assessed = assess_article(article(
        title="A randomized controlled trial",
        abstract="RESULTS: Patients were randomized and outcomes compared.",
        types=("Randomized Controlled Trial",),
    ), datetime(2026, 8, 10), topic="trial")
    assert assessed.evidence_level == "randomized_trial"
    assert assessed.study_assessment is not None
    assert assessed.study_assessment.evidence_tier == "higher_strength"


def test_ranking_prefers_design_strength_within_same_section():
    rct = article(title="Target randomized controlled trial", abstract="RESULTS: Patients randomized.", types=("Randomized Controlled Trial",))
    case = article(title="Target case report", abstract="A patient was described.", types=("Case Reports",))
    ranked = rank_articles([case, rct], datetime(2026, 8, 10), topic="Target")
    assert ranked[0].assessment.study_assessment.design_family == "randomized_controlled_trial"
