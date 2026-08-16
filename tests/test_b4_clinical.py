from datetime import date
from app.models.article import AbstractSection, Article
from app.models.assessment import EvidenceAssessment, RankedArticle
from app.models.relevance import ClinicalRelevanceAssessment
from app.models.study import StudyAssessment
from app.services.clinical_extraction import extract_clinical
from app.services.report_policy import load_policy, route_report_section

def article(text, sections=()):
    return Article("b4-1", "A clinical study", text, publication_date=date(2025,1,1), abstract_sections=tuple(AbstractSection(*x) for x in sections), publication_types=("Randomized Controlled Trial",))

def test_policy_is_versioned_and_validated():
    policy=load_policy()
    assert policy["policy_id"] == "clinical_research_priority_v1"
    assert policy["policy_version"] == "1.0.0"
    assert "preclinical_gate" in policy["rules"]

def test_structured_results_extract_population_comparator_effect_and_conclusion():
    a=article("", (("METHODS", "120 patients with hypertension received drug 10 mg oral once daily for 12 weeks versus placebo."), ("RESULTS", "The primary outcome improved (RR 1.25, 95% CI 1.01-1.54, p=0.04). Adverse events were 5% versus 4%."), ("CONCLUSIONS", "Drug was tolerated in this study.")))
    x=extract_clinical(a)
    assert x.population.scope == "human"
    assert x.comparator.kind == "placebo"
    assert x.interventions[0].dose_value == "10"
    assert x.interventions[0].dose_unit == "mg"
    assert x.outcomes[0].effect_measure_type == "rr"
    assert x.outcomes[0].p_value == "p=0.04"
    assert x.authors_conclusion == "Drug was tolerated in this study."

def test_missing_abstract_is_reviewable_and_preclinical_is_not_visible():
    missing=extract_clinical(Article("b4-2", "A study", ""))
    assert missing.needs_review and "Full text review needed" in missing.warnings
    study=StudyAssessment("animal_preclinical","animal_preclinical","preclinical_only","reported","preclinical","high",False,None,"not_reported","not_reported",None,"unknown","unknown","unknown","unknown","unknown",None,None,"not_reported",(),(),(),(),"b3.1")
    assessment=EvidenceAssessment("other","Other",10,10,10,False,False,True,"available",(),(),"key_evidence",study)
    relevance=ClinicalRelevanceAssessment("b4-3","contextual",10,(),(),"included_contextual","context",None)
    section, visible, reason=route_report_section(RankedArticle(Article("b4-3","animal","mice"),assessment,relevance))
    assert (section, visible) == ("audit_only", False)
    assert "Preclinical" in reason

def test_pharmacovigilance_is_non_causal_signal():
    x=extract_clinical(article("A FAERS disproportionality study found a reporting odds ratio for adverse events."))
    assert x.safety_findings[0].signal_source_type == "disproportionality_signal"
    assert "incidence cannot be calculated" in x.safety_findings[0].limitations


def test_clinical_extraction_rejects_literature_comparisons_and_preserves_mixed_population():
    for text in (
        "Results were compared with previous reports.",
        "Results were compared with prior studies.",
        "Results were compared with published data.",
    ):
        assert extract_clinical(article(text)).comparator.status == "not_reported"
    mixed = extract_clinical(article("Patients and mice were evaluated in parallel."))
    assert mixed.population.scope == "mixed_human_preclinical"
    assert extract_clinical(article("Patients were evaluated. Preclinical background was discussed.")).population.scope == "human"
    assert extract_clinical(article("Clinical evaluation was conducted.")).population.scope == "unclear"


def test_outcome_and_effect_extraction_reject_unsafe_fragments_and_keep_named_measures():
    for text in (
        "RESULTS: 13,; 93,; 0.3,; p=0.05.",
        "RESULTS: patients >=18 years were eligible, or 1 g versus 2 g was administered.",
        "RESULTS: The result was p=0.03; OR = 2.",
    ):
        extracted = extract_clinical(article(text))
        assert not extracted.outcomes
    valid = extract_clinical(article("RESULTS: Pain severity at day 7 improved (OR = 0.25, 95% CI 0.10-0.60)."))
    assert valid.outcomes[0].name == "Pain severity at day 7 improved"
    assert valid.outcomes[0].effect_measure_type == "or"
    assert valid.outcomes[0].effect_value == "OR = 0.25"
    risk = extract_clinical(article("RESULTS: Lesion healing by day 14 improved (risk ratio = 1.25, 95% CI 1.01-1.54)."))
    assert risk.outcomes[0].effect_measure_type == "risk ratio"
    assert risk.outcomes[0].effect_value == "risk ratio = 1.25"
    mixed = extract_clinical(article("METHODS: Patients received 1 g versus 2 g. RESULTS: Pain severity improved (OR = 0.25)."))
    assert mixed.outcomes[0].name == "Pain severity improved"
    assert mixed.outcomes[0].effect_value == "OR = 0.25"


def test_population_extraction_rejects_malformed_event_fragments_and_preserves_enrolled_people():
    for text in (
        "In 13 patients, toxicity was the only valacyclovir-related toxicity.",
        "RESULTS: patients (13, p=0.03) improved.",
        "RESULTS: patients with antivirals monotherapy and 0.3 had an outcome.",
    ):
        population = extract_clinical(article(text)).population
        assert population.description is None
        assert population.scope in {"human", "unclear"}
    valid = extract_clinical(article("METHODS: Immunocompromised patients aged 18 years or older were enrolled."))
    assert valid.population.description == "Immunocompromised patients aged 18 years or older were enrolled"


def test_intervention_extraction_rejects_control_words_and_keeps_supported_regimens():
    controls = extract_clinical(article(
        "METHODS: Patients received versus 2 g, either 1 g, or 3 g, and 4 g, "
        "compared 5 g, group 6 g, arm 7 g, or treatment 8 g."
    ))
    assert controls.interventions[0].status == "not_reported"

    compared = extract_clinical(article(
        "METHODS: Immunocompetent adults with herpes zoster were assigned to "
        "acyclovir 800 mg three times daily versus famciclovir 500 mg three times daily."
    ))
    assert [item.normalized_name for item in compared.interventions] == ["acyclovir", "famciclovir"]

    either = extract_clinical(article(
        "METHODS: Participants received either acyclovir 800 mg or famciclovir 500 mg."
    ))
    assert [item.normalized_name for item in either.interventions] == ["acyclovir", "famciclovir"]

    source_text = (
        "METHODS: Immunocompromised patients were randomized to receive oral "
        "valacyclovir, 1 g TID versus 2 g TID."
    )
    source = article(source_text)
    regimens = extract_clinical(source)
    assert [(item.normalized_name, item.dose_value, item.dose_unit, item.frequency) for item in regimens.interventions] == [
        ("valacyclovir", "1", "g", "TID"),
        ("valacyclovir", "2", "g", "TID"),
    ]
    assert source.abstract == source_text


def test_population_extraction_rejects_fragmentary_spans_and_keeps_coherent_people():
    for text in (
        "METHODS: In patients treated, outcomes were assessed.",
        "METHODS: While the patients in the red-light group received treatment, outcomes were assessed.",
        "METHODS: Participants were included.",
        "METHODS: Patients were randomly assigned.",
        "METHODS: Patients received treatment.",
        "RESULTS: Two of the three patients treated for herpes zoster improved.",
        "RESULTS: Of herpes zoster in immunocompetent patients: results of a randomized trial.",
    ):
        population = extract_clinical(article(text)).population
        assert population.description is None
        assert population.status == "not_reported"

    for text, expected in (
        ("METHODS: 54 inpatients with HZ were divided into three groups.", "54 inpatients with HZ were divided"),
        ("METHODS: 719 newly diagnosed multiple myeloma patients were analyzed.", "719 newly diagnosed multiple myeloma patients were analyzed"),
        ("METHODS: Children enrolled in the pharmacokinetic study were evaluated.", "Children enrolled in the pharmacokinetic study"),
    ):
        assert extract_clinical(article(text)).population.description == expected


def test_safety_extraction_keeps_complete_sentence_and_raw_abstract_unchanged():
    source_text = "Background. Grade 1 nausea and emesis, which occurred in five patients was the only valacyclovir-related toxicity."
    extracted = extract_clinical(article(source_text))
    assert extracted.safety_findings[0].event_name == "Grade 1 nausea and emesis, which occurred in five patients was the only valacyclovir-related toxicity."
    assert extracted.safety_findings[0].provenance[0].supporting_span == extracted.safety_findings[0].event_name
    assert article(source_text).abstract == source_text
    assert extract_clinical(article("No adverse events were described.")).safety_findings
    assert not extract_clinical(article("No safety statement was available.")).safety_findings
