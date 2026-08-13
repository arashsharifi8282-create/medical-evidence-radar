"""Offline regression coverage for Phase B3 study-design triage."""

from datetime import datetime

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


def test_comparator_follow_up_and_data_source_are_preserved():
    result = assess_study_design(article(
        abstract="METHODS: Patients were compared with placebo for 12 weeks using an EHR database.",
    ))
    assert result.comparator_status == "reported"
    assert "placebo" in result.comparator_text.casefold()
    assert result.follow_up_text is not None
    assert result.data_source_type == "EHR"


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
