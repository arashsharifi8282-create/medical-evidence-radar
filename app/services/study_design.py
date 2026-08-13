"""Deterministic, conservative study-design and evidence-strength triage.

The classifier uses only normalized PubMed metadata and abstract text. It is
not a full-text appraisal, GRADE assessment, or formal risk-of-bias review.
"""

from __future__ import annotations

import re

from app.models.article import Article
from app.models.study import StudyAssessment, SupportingSpan

RULE_VERSION = "b3.1"
_PRECLINICAL = re.compile(r"\b(?:animal model|animals?|mice|mouse|rats?|murine|zebrafish)\b|\b(?:in\s+vitro|cell\s+line|ex\s+vivo)\b", re.I)
_HUMAN = re.compile(r"\b(?:human|humans|patients?|participants?|subjects?|volunteers?|cohort|hospitalized|pregnan(?:t|cy)|clinical trial)\b", re.I)
_RESULTS = re.compile(r"\b(?:results?|findings?|found|demonstrated|observed|concluded|conclusions?)\b", re.I)
_METHODS = re.compile(r"\b(?:methods?|methodology|performed|conducted|randomi[sz]ed|enrolled|included)\b", re.I)
_MIXED_SCOPE = re.compile(r"\b(?:patients?|participants?|humans?)\b.{0,80}\b(?:mice|mouse|rats?|animals?|in\s+vitro|cell\s+line)\b|\b(?:mice|mouse|rats?|animals?|in\s+vitro|cell\s+line)\b.{0,80}\b(?:patients?|participants?|humans?)\b", re.I)
_NUMBER = r"(?P<n>(?<![\d,])(?:\d{1,3}(?:,\d{3})+|\d{1,6})(?![\d,]))"
_NUMBER_WORD = r"(?P<w>(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|and|-|\s)+)"
_POP_DESCRIPTOR = r"(?:(?!(?:study|studies|followed|assessed|treated|included|randomized|enrolled|these|those|the|of|and)\b)[A-Za-z-]+\s+){0,2}"


def assess_study_design(article: Article) -> StudyAssessment:
    """Return a source-linked B3 assessment without inventing missing values."""
    text = _article_text(article)
    lower = text.casefold()
    spans: list[SupportingSpan] = []
    signals: list[str] = []

    def signal(source_type: str, phrase: str, rule_id: str, field: str = "title_or_abstract") -> None:
        signals.append(f"{source_type}:{phrase}")
        spans.append(SupportingSpan(field, source_type, phrase, rule_id))

    design_family, design_subtype, design_rule = _classify_design(article, lower)
    if design_rule:
        signal("publication_type" if design_rule.startswith("PT_") else "text", design_rule, design_rule)

    population_scope = _population_scope(article, design_family)
    if population_scope == "mixed":
        signal("text", "human and preclinical signals", "POP_MIXED")
    elif population_scope == "preclinical_only":
        signal("text", "preclinical signal", "POP_PRECLINICAL")
    elif population_scope == "human":
        signal("text", "human signal", "POP_HUMAN")

    result_status = _result_status(article, text, design_family)
    sample_size, sample_status, sample_spans = _sample_size(article)
    spans.extend(sample_spans)
    if sample_status == "reported":
        signals.append("sample_size:reported")
    elif sample_status == "ambiguous":
        signals.append("sample_size:ambiguous")

    comparator_status, comparator_text, comparator_span = _comparator(text)
    if comparator_span:
        spans.append(comparator_span)
        signals.append("comparator:reported")

    treatment_duration_text, treatment_span = _treatment_duration(text)
    if treatment_span:
        spans.append(treatment_span)
        signals.append("treatment_duration:reported")

    follow_up_text, follow_span = _follow_up(text)
    if follow_span:
        spans.append(follow_span)
        signals.append("follow_up:reported")

    randomized = _tri_state(text, r"\b(?:randomi[sz]ed|randomization|random allocation)\b", r"\bnon[- ]?randomi[sz]ed\b")
    blinded = _tri_state(text, r"\b(?:double|triple|single)[- ]blind(?:ed)?\b|\bblinded\b", r"\b(?:open[- ]label|unblinded)\b")
    prospective = _tri_state(text, r"\bprospective\b", r"\bnon[- ]?prospective\b")
    retrospective = _tri_state(text, r"\bretrospective\b", r"\bnon[- ]?retrospective\b")
    multicenter = _tri_state(text, r"\bmulticenter\b|\bmulti[- ]center\b", r"\bsingle[- ]center\b")

    data_source_type = _data_source_type(text)
    evidence_tier, evidence_rule = _evidence_tier(
        design_family, design_subtype, result_status, population_scope,
        bool(article.abstract or article.abstract_sections),
    )
    if evidence_rule:
        signals.append(f"evidence_tier:{evidence_rule}")
    limitations = _limitations(
        article, design_family, design_subtype, population_scope, result_status,
        sample_status, comparator_status, follow_up_text, multicenter, evidence_tier,
    )
    reasons = _reasons(
        design_family, design_subtype, evidence_tier, result_status, population_scope,
        sample_status, comparator_status, limitations,
    )
    needs_review = (
        design_family == "unknown"
        or "conflicting_design_signals" in limitations
        or "abstract_missing" in limitations
        or sample_status == "ambiguous"
    )
    confidence = "high" if design_family != "unknown" and not needs_review else "low" if design_family == "unknown" else "medium"

    return StudyAssessment(
        design_family=design_family,
        design_subtype=design_subtype,
        population_scope=population_scope,
        result_status=result_status,
        evidence_tier=evidence_tier,
        confidence=confidence,
        needs_review=needs_review,
        sample_size=sample_size,
        sample_size_status=sample_status,
        comparator_status=comparator_status,
        comparator_text=comparator_text,
        randomized=randomized,
        blinded=blinded,
        prospective=prospective,
        retrospective=retrospective,
        multicenter=multicenter,
        treatment_duration_text=treatment_duration_text,
        follow_up_text=follow_up_text,
        data_source_type=data_source_type,
        limitation_codes=tuple(limitations),
        matched_signals=tuple(dict.fromkeys(signals)),
        supporting_spans=tuple(spans),
        assessment_reasons=tuple(reasons),
        rule_version=RULE_VERSION,
    )


def _article_text(article: Article) -> str:
    sections = " ".join(f"{s.label}: {s.text}" for s in article.abstract_sections)
    return " ".join(x for x in (article.title, article.abstract, sections, " ".join(article.keywords)) if x)


def _pt(article: Article) -> set[str]:
    return {re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip() for value in article.publication_types}


def _classify_design(article: Article, lower: str) -> tuple[str, str, str]:
    pts = _pt(article)
    if _contains_any(pts, "network meta analysis") or re.search(r"\bnetwork meta[- ]analysis\b", lower):
        return "systematic_review_meta_analysis", "network_meta_analysis", "PT_NETWORK_META_ANALYSIS"
    if "systematic review" in pts and ("meta analysis" in pts or re.search(r"\bmeta[- ]analysis\b", lower)):
        return "systematic_review_meta_analysis", "systematic_review_meta_analysis", "PT_SYSTEMATIC_META"
    if _contains_any(pts, "meta analysis") or re.search(r"\bsystematic review and meta[- ]analysis\b", lower):
        return "systematic_review_meta_analysis", "systematic_review_meta_analysis", "PT_META_ANALYSIS"
    if "systematic review" in pts or re.search(r"\bsystematic review\b", lower):
        return "systematic_review_without_meta_analysis", "systematic_review_without_meta_analysis", "PT_SYSTEMATIC_REVIEW"
    if "scoping review" in pts or re.search(r"\bscoping review\b", lower):
        return "scoping_review", "scoping_review", "PT_SCOPING_REVIEW"
    if "practice guideline" in pts or "guideline" in pts or "consensus development conference" in pts:
        return "guideline_or_consensus", "guideline_or_consensus", "PT_GUIDELINE"
    if "protocol" in pts or re.search(r"\b(?:study|trial) protocol\b", lower):
        return "protocol", "protocol", "PT_PROTOCOL" if "protocol" in pts else "TEXT_PROTOCOL"
    if "case series" in pts or re.search(r"\bcase series\b", lower):
        return "case_series", "case_series", "PT_CASE_SERIES" if "case series" in pts else "TEXT_CASE_SERIES"
    if "case reports" in pts or re.search(r"\bcase report\b", lower):
        return "case_report", "case_report", "PT_CASE_REPORT" if "case reports" in pts else "TEXT_CASE_REPORT"
    if "pharmacovigilance" in lower or "faers" in lower or "disproportionality" in lower or "reporting odds ratio" in lower or "spontaneous reports" in lower:
        return "pharmacovigilance_disproportionality", "pharmacovigilance_disproportionality", "TEXT_PHARMACOVIGILANCE"
    if "randomized controlled trial" in pts or "randomised controlled trial" in pts or "controlled clinical trial" in pts:
        return "randomized_controlled_trial", "randomized_controlled_trial", "PT_RCT"
    if re.search(r"\brandomi[sz]ed\b", lower) and re.search(r"\btrial\b", lower):
        return "randomized_controlled_trial", "randomized_controlled_trial", "TEXT_RCT"
    if re.search(r"\bnon[- ]?randomi[sz]ed\b|\bnon[- ]?randomized intervention", lower):
        return "nonrandomized_interventional_study", "nonrandomized_interventional_study", "TEXT_NONRANDOMIZED_INTERVENTION"
    if "diagnostic accuracy" in pts or re.search(r"\bdiagnostic accuracy\b", lower):
        return "diagnostic_accuracy", "diagnostic_accuracy", "PT_DIAGNOSTIC"
    if "case control studies" in pts or re.search(r"\bcase[- ]control\b", lower):
        return "case_control", "case_control", "PT_CASE_CONTROL" if "case control studies" in pts else "TEXT_CASE_CONTROL"
    if "cross sectional studies" in pts or re.search(r"\bcross[- ]sectional\b", lower):
        return "cross_sectional", "cross_sectional", "PT_CROSS_SECTIONAL" if "cross sectional studies" in pts else "TEXT_CROSS_SECTIONAL"
    if re.search(r"\bretrospective\s+cohort\b|\bretrospective\b", lower):
        return "retrospective_cohort", "retrospective_cohort", "TEXT_RETROSPECTIVE_COHORT"
    if "observational study" in pts or re.search(r"\bobservational study\b", lower):
        return ("prospective_cohort", "prospective_cohort", "TEXT_PROSPECTIVE_OBSERVATIONAL") if re.search(r"\bprospective\b", lower) else ("nonrandomized_interventional_study", "nonrandomized_interventional_study", "TEXT_OBSERVATIONAL")
    if "cohort studies" in pts or re.search(r"\bprospective cohort\b", lower):
        return "prospective_cohort", "prospective_cohort", "PT_OR_TEXT_PROSPECTIVE_COHORT"
    if re.search(r"\bpharmacokinetic|\bpharmacodynamic|\bpharmacokinetics\b", lower):
        return "pharmacokinetic_pharmacodynamic", "pharmacokinetic_pharmacodynamic", "TEXT_PKPD"
    if "animal" in pts or "animals" in pts or "in vitro" in lower or _PRECLINICAL.search(lower):
        if _explicit_mixed_scope(article):
            return "mixed_human_preclinical", "mixed_human_preclinical", "TEXT_MIXED_PRECLINICAL"
        return ("in_vitro", "in_vitro", "TEXT_IN_VITRO") if re.search(r"\bin\s+vitro\b|\bcell line\b", lower) else ("animal_preclinical", "animal_preclinical", "TEXT_ANIMAL")
    if "review" in pts or re.search(r"\bnarrative review\b|\breview\b", lower):
        return "narrative_review", "narrative_review", "PT_OR_TEXT_NARRATIVE_REVIEW"
    if pts.intersection({"editorial", "comment", "letter"}) or re.search(r"\b(?:editorial|commentary|letter)\b", lower):
        return "editorial_commentary_letter", "editorial_commentary_letter", "PT_OR_TEXT_EDITORIAL"
    return "unknown", "unknown", "TEXT_UNKNOWN"


def _population_scope(article: Article, design_family: str) -> str:
    text = _article_text(article)
    primary_sections = " ".join(
        section.text
        for section in article.abstract_sections
        if section.label.casefold() in {"methods", "results", "patients", "participants"}
    )
    fallback_primary = re.split(r"\b(?:in conclusion|conclusion|conclusions)\b", article.abstract, maxsplit=1, flags=re.I)[0]
    primary_text = " ".join(part for part in (article.title, primary_sections or fallback_primary) if part)
    pre = bool(_PRECLINICAL.search(text))
    human = bool(_HUMAN.search(text))
    primary_pre = bool(_PRECLINICAL.search(primary_text))
    primary_human = bool(_HUMAN.search(primary_text))
    if design_family in {"editorial_commentary_letter", "narrative_review", "systematic_review_meta_analysis", "systematic_review_without_meta_analysis"}:
        return "not_applicable"
    if design_family in {"randomized_controlled_trial", "prospective_cohort", "retrospective_cohort", "case_control", "cross_sectional", "diagnostic_accuracy", "nonrandomized_interventional_study", "pharmacokinetic_pharmacodynamic", "case_report", "case_series"}:
        if _MIXED_SCOPE.search(primary_text):
            return "mixed"
        if primary_human:
            return "human"
        if primary_pre:
            return "preclinical_only"
    if pre and human:
        return "mixed"
    if pre:
        return "preclinical_only"
    if human:
        return "human"
    return "unclear"


def _result_status(article: Article, text: str, design_family: str) -> str:
    if not article.abstract and not article.abstract_sections:
        return "not_reported"
    if design_family == "protocol" and not re.search(r"\bresults?\b", text, re.I):
        return "not_reported"
    if article.abstract_sections and any(s.label.casefold() in {"results", "conclusions", "findings"} for s in article.abstract_sections):
        return "reported"
    return "reported" if _RESULTS.search(text) else "unclear"


def _sample_size(article: Article) -> tuple[int | None, str, list[SupportingSpan]]:
    text = _article_text(article)
    primary_patterns = [
        ("enrolled", rf"\b{_NUMBER}\s+{_POP_DESCRIPTOR}(?:patients?|participants?|subjects?|children|adults|individuals)\s+were\s+enrolled\b"),
        ("enrolled", rf"\b{_NUMBER}\s+{_POP_DESCRIPTOR}(?:patients?|participants?|subjects?|children|adults|individuals)\s+enrolled\b"),
        ("randomized", rf"\b{_NUMBER}\s+{_POP_DESCRIPTOR}(?:patients?|participants?|subjects?|children|adults|individuals)\s+(?:were\s+)?randomi[sz]ed\b"),
        ("randomized", rf"\brandomi[sz]ed\b[^.;]{{0,80}}\b{_NUMBER}\s+{_POP_DESCRIPTOR}(?:patients?|participants?|subjects?|children|adults|individuals)\b"),
        ("included", rf"\b{_NUMBER}\s+{_POP_DESCRIPTOR}(?:patients?|participants?|subjects?|children|adults|individuals)\s+(?:were\s+)?included\b"),
        ("included", rf"\bincluded\s+{_NUMBER}\s+{_POP_DESCRIPTOR}(?:patients?|participants?|subjects?|children|adults|individuals)\b"),
        ("participants", rf"\b{_NUMBER}\s+cases?\b"),
        ("participants", rf"\b{_NUMBER}\s+(?:participants?|patients?|subjects?|children|adults|individuals)\b"),
        ("participants", rf"\b{_NUMBER}\s+{_POP_DESCRIPTOR}(?:patients?|participants?|subjects?|children|adults|individuals)\b"),
        ("participants", rf"\bn\s*=\s*{_NUMBER}\s+{_POP_DESCRIPTOR}(?:patients?|participants?|subjects?|children|adults|individuals|cases?)\b"),
        ("participants", rf"\b(?:sample|series|cohort)\s+of\s+{_NUMBER}\b"),
    ]
    secondary_patterns = [
        ("completed", rf"\b{_NUMBER}\s+{_POP_DESCRIPTOR}(?:patients?|participants?|subjects?|children|adults|individuals)\s+completed\b"),
        ("completed", rf"\bcompleted\b[^.;]{{0,80}}\b{_NUMBER}\s+{_POP_DESCRIPTOR}(?:patients?|participants?|subjects?|children|adults|individuals)\b"),
        ("analyzed", rf"\b{_NUMBER}\s+{_POP_DESCRIPTOR}(?:patients?|participants?|subjects?|children|adults|individuals)\s+(?:were\s+)?analy[sz]ed\b"),
        ("analyzed", rf"\banaly[sz]ed\b[^.;]{{0,80}}\b{_NUMBER}\s+{_POP_DESCRIPTOR}(?:patients?|participants?|subjects?|children|adults|individuals)\b"),
        ("pk_data", rf"\b{_NUMBER}\s+{_POP_DESCRIPTOR}(?:patients?|participants?|subjects?|children|adults|individuals)\s+(?:had|with)\s+PK data\b"),
        ("pk_data", rf"\bPK data\b[^.;]{{0,40}}\bfor\s+{_NUMBER}\s+{_POP_DESCRIPTOR}(?:patients?|participants?|subjects?|children|adults|individuals)\b"),
        ("pk_data", rf"\bpharmacokinetic data\b[^.;]{{0,40}}\bfor\s+{_NUMBER}\s+{_POP_DESCRIPTOR}(?:patients?|participants?|subjects?|children|adults|individuals)\b"),
    ]
    primary = _collect_population_counts(text, primary_patterns)
    secondary = _collect_population_counts(text, secondary_patterns)
    spans = [SupportingSpan("abstract", kind, snippet, rule) for kind, _, snippet, rule in secondary]
    if primary:
        roles = ("enrolled", "randomized", "included", "participants")
        for role in roles:
            role_items = [(value, snippet, rule) for item_role, value, snippet, rule in primary if item_role == role]
            unique_values = {value for value, _, _ in role_items}
            if len(unique_values) == 1:
                value, snippet, rule = role_items[0]
                return value, "reported", [SupportingSpan("abstract", "sample_size", snippet, rule), *spans]
            if len(unique_values) > 1:
                joined = "; ".join(snippet for _, snippet, _ in role_items)
                return None, "ambiguous", [SupportingSpan("abstract", "sample_size", joined, "SAMPLE_AMBIGUOUS"), *spans]
    study_count_match = re.search(rf"\b{_NUMBER}\s+stud(?:y|ies)\b", text, re.I)
    participant_count_match = re.search(rf"\b{_NUMBER}\s+(?:participants?|patients?|subjects?|individuals)\b", text, re.I)
    if study_count_match and participant_count_match:
        participant_value = _parse_int(participant_count_match.group("n"))
        return participant_value, "reported", [
            SupportingSpan("abstract", "sample_size", participant_count_match.group(0), "SAMPLE_PARTICIPANT_COUNT"),
            SupportingSpan("abstract", "study_count", study_count_match.group(0), "STUDY_COUNT_SEPARATE_FROM_SAMPLE_SIZE"),
            *spans,
        ]
    return None, "not_reported", []


def _comparator(text: str) -> tuple[str, str | None, SupportingSpan | None]:
    match = re.search(r"\b(?:placebo|usual care|active comparator|historical control|no comparator)\b|\b(?:compared with|compared to|versus|vs\.?)[^.;,]{0,80}", text, re.I)
    if not match:
        return "not_reported", None, None
    value = match.group(0).strip()
    status = "not_applicable" if re.search(r"no comparator", value, re.I) else "reported"
    return status, value, SupportingSpan("abstract", "comparator", value, "COMPARATOR_EXPLICIT")


def _follow_up(text: str) -> tuple[str | None, SupportingSpan | None]:
    patterns = [
        r"\bfollowed\s+(?:patients?|participants?|subjects?)\s+for\s+\d+\s*(?:days?|weeks?|months?|years?)\b",
        r"\bfollow(?:ed|[- ]up)?\s+(?:for|through|until)\s+\d+\s*(?:days?|weeks?|months?|years?)\b",
        r"\bassessed\s+up\s+to\s+\d+\s*(?:days?|weeks?|months?|years?)\b",
        r"\bat\s+\d+\s*(?:days?|weeks?|months?|years?)\s+follow[- ]up\b",
        r"\bup\s+to\s+\d+\s*(?:days?|weeks?|months?|years?)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            value = match.group(0).strip()
            return value, SupportingSpan("abstract", "follow_up", value, "FOLLOW_UP_EXPLICIT")
    return None, None


def _treatment_duration(text: str) -> tuple[str | None, SupportingSpan | None]:
    patterns = [
        r"\b(?:treated|receive|received|receiving|administered|dosed?|therapy)\b[^.;]{0,220}\bfor\s+\d+\s*(?:days?|weeks?|months?|years?)\b",
        r"\bcompared\s+with\s+[^.;]{0,120}\bfor\s+\d+\s*(?:days?|weeks?|months?|years?)\b",
        r"\bfor\s+\d+\s*(?:days?|weeks?|months?|years?)\s+of\s+treatment\b",
        r"\bdosing\s+for\s+\d+\s*(?:days?|weeks?|months?|years?)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            value = match.group(0).strip()
            return value, SupportingSpan("abstract", "treatment_duration", value, "TREATMENT_DURATION_EXPLICIT")
    return None, None


def _tri_state(text: str, true_pattern: str, false_pattern: str) -> str:
    if re.search(true_pattern, text, re.I):
        return "true"
    if re.search(false_pattern, text, re.I):
        return "false"
    return "unknown"


def _data_source_type(text: str) -> str:
    for label, pattern in (
        ("FAERS", r"\bFAERS\b"),
        ("spontaneous_reports", r"\bspontaneous reports?\b"),
        ("registry", r"\bregistr(?:y|ies)\b"),
        ("claims", r"\bclaims?\b"),
        ("EHR", r"\b(?:EHR|electronic health records?)\b"),
        ("database", r"\bdatabase(?:s)?\b"),
        ("chart_review", r"\bmedical records?\b|\bchart review\b"),
    ):
        if re.search(pattern, text, re.I):
            return label
    return "not_reported"


def _evidence_tier(design_family: str, subtype: str, result_status: str, population_scope: str, has_abstract: bool) -> tuple[str, str]:
    if population_scope == "preclinical_only" or design_family in {"animal_preclinical", "in_vitro", "mixed_human_preclinical"}:
        return "preclinical", "PRECLINICAL_ONLY"
    if design_family == "pharmacovigilance_disproportionality":
        return "signal_only", "PHARMACOVIGILANCE_SIGNAL_ONLY"
    if design_family in {"protocol", "editorial_commentary_letter", "unknown", "guideline_or_consensus"} or not has_abstract:
        return "not_assessable", "NOT_ASSESSABLE_METADATA"
    if design_family == "systematic_review_meta_analysis":
        return ("higher_strength", "SYSTEMATIC_META_RESULTS") if result_status == "reported" else ("moderate_strength", "SYSTEMATIC_META_LIMITED")
    if design_family == "randomized_controlled_trial":
        return ("higher_strength", "RCT_RESULTS") if result_status == "reported" else ("moderate_strength", "RCT_LIMITED")
    if design_family == "systematic_review_without_meta_analysis":
        return "moderate_strength", "SYSTEMATIC_NO_META"
    if design_family in {"prospective_cohort", "retrospective_cohort", "case_control", "cross_sectional", "diagnostic_accuracy", "nonrandomized_interventional_study", "pharmacokinetic_pharmacodynamic"}:
        return ("moderate_strength", "OBSERVATIONAL_REPORTED") if result_status == "reported" else ("limited_strength", "OBSERVATIONAL_LIMITED")
    if design_family in {"case_report", "case_series", "narrative_review", "scoping_review"}:
        return "limited_strength", "DESCRIPTIVE_OR_NARRATIVE"
    return "not_assessable", "UNKNOWN_DESIGN"


def _limitations(article: Article, family: str, subtype: str, population: str, result_status: str, sample_status: str, comparator_status: str, follow_up: str | None, multicenter: str, tier: str) -> list[str]:
    values: list[str] = []
    if not article.abstract and not article.abstract_sections:
        values.append("abstract_missing")
    if not _METHODS.search(_article_text(article)):
        values.append("methods_not_reported")
    if sample_status != "reported":
        values.append("sample_size_not_reported")
    if comparator_status == "not_reported":
        values.append("comparator_not_reported")
    if family in {"randomized_controlled_trial", "prospective_cohort", "retrospective_cohort", "case_control", "cross_sectional", "diagnostic_accuracy"} and not follow_up:
        values.append("follow_up_not_reported")
    if family in {"prospective_cohort", "retrospective_cohort", "case_control", "cross_sectional", "diagnostic_accuracy", "nonrandomized_interventional_study"}:
        values.append("nonrandomized")
    if family == "retrospective_cohort":
        values.append("retrospective_design")
    if multicenter == "false":
        values.append("single_center")
    if family in {"case_report", "case_series"}:
        values.append("case_report_or_series")
    if family == "protocol":
        values.append("protocol_no_results")
    if population == "preclinical_only":
        values.append("preclinical_only")
    if population == "mixed":
        values.append("mixed_population")
    if family == "pharmacovigilance_disproportionality":
        values.extend(["pharmacovigilance_reporting_bias", "pharmacovigilance_no_incidence", "pharmacovigilance_no_causality"])
    if comparator_status == "not_applicable":
        values.append("uncontrolled_study")
    if family == "unknown":
        values.append("design_unclear")
    if result_status == "unclear":
        values.append("methods_not_reported")
    if sample_status == "ambiguous":
        values.append("design_unclear")
    return list(dict.fromkeys(values))


def _reasons(family: str, subtype: str, tier: str, result_status: str, population: str, sample_status: str, comparator_status: str, limitations: list[str]) -> list[str]:
    reasons = [f"Design classified as {subtype} from prioritized PubMed metadata and explicit abstract signals.", f"Evidence tier {tier} is an abstract/metadata-based triage, not a formal quality assessment."]
    if result_status != "reported":
        reasons.append("Results were not sufficiently reported in the available abstract.")
    if population in {"preclinical_only", "mixed"}:
        reasons.append(f"Population scope is {population}; it is not silently treated as human clinical evidence.")
    if sample_status != "reported":
        reasons.append("Sample size was not assigned unless the text connected a number to a study population.")
    if comparator_status == "not_reported":
        reasons.append("Comparator was not reported in the available abstract.")
    return reasons


def _contains_any(values: set[str], needle: str) -> bool:
    return any(needle in value for value in values)


def _explicit_mixed_scope(article: Article) -> bool:
    texts = [article.title, article.abstract, *(section.text for section in article.abstract_sections)]
    return any(_MIXED_SCOPE.search(text or "") for text in texts)


def _parse_int(value: str) -> int:
    return int(value.replace(",", ""))


def _collect_population_counts(text: str, patterns: list[tuple[str, str]]) -> list[tuple[str, int, str, str]]:
    items: list[tuple[str, int, str, str]] = []
    seen: set[tuple[str, int]] = set()
    for role, pattern in patterns:
        for match in re.finditer(pattern, text, re.I):
            value = _parse_int(match.group("n"))
            snippet = match.group(0)
            if role in {"enrolled", "randomized", "included"} and re.search(r"\band\b.{0,20}\b(?:patients?|participants?|subjects?|children|adults|individuals|cases?)\b", snippet, re.I):
                continue
            key = (role, value)
            if key in seen or value == 0:
                continue
            seen.add(key)
            rule = {
                "enrolled": "SAMPLE_ENROLLED",
                "randomized": "SAMPLE_RANDOMIZED",
                "included": "SAMPLE_INCLUDED",
                "participants": "SAMPLE_PARTICIPANT_COUNT",
                "completed": "SAMPLE_COMPLETED",
                "analyzed": "SAMPLE_ANALYZED",
                "pk_data": "SAMPLE_PK_DATA",
            }[role]
            items.append((role, value, snippet, rule))
        word_pattern = pattern.replace(_NUMBER, _NUMBER_WORD)
        for match in re.finditer(word_pattern, text, re.I):
            value = _parse_number_phrase(match.group("w"))
            if value is None:
                continue
            snippet = match.group(0)
            if role in {"enrolled", "randomized", "included"} and re.search(r"\band\b.{0,20}\b(?:patients?|participants?|subjects?|children|adults|individuals|cases?)\b", snippet, re.I):
                continue
            key = (role, value)
            if key in seen or value == 0:
                continue
            seen.add(key)
            rule = {
                "enrolled": "SAMPLE_ENROLLED",
                "randomized": "SAMPLE_RANDOMIZED",
                "included": "SAMPLE_INCLUDED",
                "participants": "SAMPLE_PARTICIPANT_COUNT",
                "completed": "SAMPLE_COMPLETED",
                "analyzed": "SAMPLE_ANALYZED",
                "pk_data": "SAMPLE_PK_DATA",
            }[role]
            items.append((role, value, snippet, rule))
    return items


def _parse_number_phrase(value: str) -> int | None:
    words = [token for token in re.split(r"[\s-]+", value.casefold()) if token and token != "and"]
    units = {
        "zero": 0,
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
        "eleven": 11,
        "twelve": 12,
        "thirteen": 13,
        "fourteen": 14,
        "fifteen": 15,
        "sixteen": 16,
        "seventeen": 17,
        "eighteen": 18,
        "nineteen": 19,
        "twenty": 20,
        "thirty": 30,
        "forty": 40,
        "fifty": 50,
        "sixty": 60,
        "seventy": 70,
        "eighty": 80,
        "ninety": 90,
    }
    total = 0
    current = 0
    for word in words:
        if word in units:
            current += units[word]
        elif word == "hundred":
            current = max(1, current) * 100
        elif word == "thousand":
            total += max(1, current) * 1000
            current = 0
        else:
            return None
    value_int = total + current
    return value_int if value_int > 0 else None
