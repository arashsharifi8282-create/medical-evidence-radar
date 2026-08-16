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
