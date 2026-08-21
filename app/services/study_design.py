"""Deterministic, conservative study-design and evidence-strength triage.

The classifier uses only normalized PubMed metadata and abstract text. It is
not a full-text appraisal, GRADE assessment, or formal risk-of-bias review.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.models.article import Article
from app.models.study import StudyAssessment, SupportingSpan

RULE_VERSION = "b3.1"
_PRECLINICAL = re.compile(r"\b(?:animal model|animals?|mice|mouse|rats?|murine|zebrafish|preclinical)\b|\b(?:in\s+vitro|cell\s+line|ex\s+vivo)\b", re.I)
_HUMAN = re.compile(r"\b(?:human|humans|patients?|participants?|subjects?|volunteers?|cohort|hospitalized|pregnan(?:t|cy)|clinical trial)\b", re.I)
_RESULTS = re.compile(r"\b(?:results?|findings?|found|demonstrated|observed|concluded|conclusions?)\b", re.I)
_METHODS = re.compile(r"\b(?:methods?|methodology|performed|conducted|randomi[sz]ed|enrolled|included)\b", re.I)
_MIXED_SCOPE = re.compile(r"\b(?:patients?|participants?|humans?)\b\s+(?:and|with|alongside|as\s+well\s+as)\s+\b(?:mice|mouse|rats?|animals?|preclinical|in\s+vitro|cell\s+line)\b|\b(?:mice|mouse|rats?|animals?|preclinical|in\s+vitro|cell\s+line)\b\s+(?:and|with|alongside|as\s+well\s+as)\s+\b(?:patients?|participants?|humans?)\b", re.I)
_NUMBER = r"(?P<n>(?<![\d,])(?:\d{1,3}(?:,\d{3})+|\d{1,6})(?![\d,]))"
_NUMBER_WORD = r"(?P<w>(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|and|-|\s)+)"
_POP_DESCRIPTOR = r"(?:(?!(?:study|studies|followed|assessed|treated|included|randomized|enrolled|these|those|the|of|and|in|at|per|arm|group)\b)[A-Za-z-]+\s+){0,2}"


@dataclass(frozen=True)
class _DesignSignal:
    family: str
    subtype: str
    source_type: str
    field: str
    text: str
    rule_id: str
    strength: int


# A source's reliability is fixed: curated PubMed publication types and named
# structured abstract sections outrank title, which outranks free abstract and
# keyword text.  Only incompatible signals at the winning reliability level
# are unresolved conflicts; weaker incidental phrases remain auditable.
_DESIGN_STRENGTH = {
    "publication_type": 3,
    "structured_abstract": 3,
    "title": 2,
    "abstract": 1,
    "keyword": 1,
}
_DESIGN_ORDER = (
    "systematic_review_meta_analysis", "scoping_review", "guideline_or_consensus",
    "protocol", "case_series", "case_report", "pharmacovigilance_disproportionality",
    "randomized_controlled_trial", "nonrandomized_interventional_study", "diagnostic_accuracy",
    "case_control", "cross_sectional", "retrospective_cohort", "prospective_cohort",
    "pharmacokinetic_pharmacodynamic", "mixed_human_preclinical", "in_vitro",
    "animal_preclinical", "systematic_review_without_meta_analysis", "narrative_review",
    "editorial_commentary_letter",
)


def assess_study_design(article: Article) -> StudyAssessment:
    """Return a source-linked B3 assessment without inventing missing values."""
    text = _article_text(article)
    spans: list[SupportingSpan] = []
    signals: list[str] = []

    def signal(source_type: str, phrase: str, rule_id: str, field: str = "title_or_abstract") -> None:
        signals.append(f"{source_type}:{phrase}")
        spans.append(SupportingSpan(field, source_type, phrase, rule_id))

    design_family, design_subtype, design_signals, design_conflict = _classify_design(article)
    for design_signal in design_signals:
        signal(design_signal.source_type, design_signal.text, design_signal.rule_id, design_signal.field)

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

    comparator_source = " ".join(section.text for section in article.abstract_sections) or article.abstract
    comparator_status, comparator_text, comparator_span = _comparator(comparator_source)
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
        sample_status, comparator_status, follow_up_text, multicenter, evidence_tier, design_conflict,
    )
    reasons = _reasons(
        design_family, design_subtype, evidence_tier, result_status, population_scope,
        sample_status, comparator_status, limitations, design_conflict,
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


def _classify_design(article: Article) -> tuple[str, str, tuple[_DesignSignal, ...], bool]:
    signals = [*_publication_type_signals(article)]
    for section in article.abstract_sections:
        signal = _text_design_signal(section.text, "structured_abstract", "abstract_sections", f"SECTION_{section.label.casefold().replace(' ', '_')}", article)
        if signal:
            signals.append(signal)
    for source_type, field, value, suffix in (
        ("title", "title", article.title, "TITLE"),
        ("abstract", "abstract", article.abstract, "ABSTRACT"),
    ):
        signal = _text_design_signal(value, source_type, field, suffix, article)
        if signal:
            signals.append(signal)
    for keyword in article.keywords:
        signal = _text_design_signal(keyword, "keyword", "keywords", "KEYWORD", article)
        if signal:
            signals.append(signal)
    if not signals:
        return "unknown", "unknown", (), False
    explicit_protocol = next((signal for signal in signals if signal.rule_id == "PT_PROTOCOL"), None)
    if explicit_protocol:
        return "protocol", "protocol", tuple(signals), False
    winning_strength = max(signal.strength for signal in signals)
    winners = [signal for signal in signals if signal.strength == winning_strength]
    families = {signal.family for signal in winners}
    if any(not _compatible_designs(left, right) for left in families for right in families):
        return "unknown", "unknown", tuple(signals), True
    winner = min(winners, key=lambda signal: _DESIGN_ORDER.index(signal.family))
    return winner.family, winner.subtype, tuple(signals), False


def _publication_type_signals(article: Article) -> list[_DesignSignal]:
    signals: list[_DesignSignal] = []
    for publication_type in article.publication_types:
        normalized = re.sub(r"[^a-z0-9]+", " ", publication_type.casefold()).strip()
        family = subtype = rule = None
        if "network meta analysis" in normalized:
            family, subtype, rule = "systematic_review_meta_analysis", "network_meta_analysis", "PT_NETWORK_META_ANALYSIS"
        elif "meta analysis" in normalized:
            family = subtype = "systematic_review_meta_analysis"; rule = "PT_META_ANALYSIS"
        elif "systematic review" in normalized:
            family = subtype = "systematic_review_without_meta_analysis"; rule = "PT_SYSTEMATIC_REVIEW"
        elif "scoping review" in normalized:
            family = subtype = "scoping_review"; rule = "PT_SCOPING_REVIEW"
        elif normalized in {"practice guideline", "guideline", "consensus development conference"}:
            family = subtype = "guideline_or_consensus"; rule = "PT_GUIDELINE"
        elif "protocol" in normalized: family = subtype = "protocol"; rule = "PT_PROTOCOL"
        elif normalized == "case series": family = subtype = "case_series"; rule = "PT_CASE_SERIES"
        elif normalized == "case reports": family = subtype = "case_report"; rule = "PT_CASE_REPORT"
        elif normalized in {"randomized controlled trial", "randomised controlled trial", "controlled clinical trial"}:
            family = subtype = "randomized_controlled_trial"; rule = "PT_RCT"
        elif normalized == "diagnostic accuracy": family = subtype = "diagnostic_accuracy"; rule = "PT_DIAGNOSTIC"
        elif normalized == "case control studies": family = subtype = "case_control"; rule = "PT_CASE_CONTROL"
        elif normalized == "cross sectional studies": family = subtype = "cross_sectional"; rule = "PT_CROSS_SECTIONAL"
        elif normalized == "observational study": family = subtype = "prospective_cohort"; rule = "PT_COHORT"
        elif normalized in {"animal", "animals"}: family = subtype = "animal_preclinical"; rule = "PT_ANIMAL"
        elif normalized == "review": family = subtype = "narrative_review"; rule = "PT_NARRATIVE_REVIEW"
        elif normalized in {"editorial", "comment", "letter"}: family = subtype = "editorial_commentary_letter"; rule = "PT_EDITORIAL"
        if family:
            signals.append(_DesignSignal(family, subtype, "publication_type", "publication_types", publication_type, rule, _DESIGN_STRENGTH["publication_type"]))
    return signals


def _text_design_signal(value: str, source_type: str, field: str, suffix: str, article: Article) -> _DesignSignal | None:
    lower = value.casefold()
    checks = (
        ("systematic_review_meta_analysis", "systematic_review_meta_analysis", r"\b(?:network )?meta[- ]analysis\b|\bsystematic review and meta[- ]analysis\b", "META_ANALYSIS"),
        ("systematic_review_without_meta_analysis", "systematic_review_without_meta_analysis", r"\bsystematic review\b", "SYSTEMATIC_REVIEW"),
        ("scoping_review", "scoping_review", r"\bscoping review\b", "SCOPING_REVIEW"),
        ("protocol", "protocol", r"\b(?:study|trial) protocol\b|\b(?:we\s+)?propos(?:e|ed)\b[^.;]{0,80}\b(?:phase\s+[iIvV/]+\s+)?trial\b", "PROTOCOL"),
        ("case_series", "case_series", r"\bcase series\b", "CASE_SERIES"),
        ("case_report", "case_report", r"\bcase report\b", "CASE_REPORT"),
        ("pharmacovigilance_disproportionality", "pharmacovigilance_disproportionality", r"\b(?:pharmacovigilance|faers|disproportionality|reporting odds ratio|spontaneous reports)\b", "PHARMACOVIGILANCE"),
        ("randomized_controlled_trial", "randomized_controlled_trial", r"\brandomi[sz]ed\b(?=[^.]{0,80}\btrial\b)|\btrial\b(?=[^.]{0,80}\brandomi[sz]ed\b)", "RCT"),
        ("nonrandomized_interventional_study", "nonrandomized_interventional_study", r"\bnon[- ]?randomi[sz]ed\b|\bnon[- ]?randomized intervention\b", "NONRANDOMIZED_INTERVENTION"),
        ("diagnostic_accuracy", "diagnostic_accuracy", r"\bdiagnostic accuracy\b", "DIAGNOSTIC"),
        ("case_control", "case_control", r"\bcase[- ]control\b", "CASE_CONTROL"),
        ("cross_sectional", "cross_sectional", r"\bcross[- ]sectional\b", "CROSS_SECTIONAL"),
        ("retrospective_cohort", "retrospective_cohort", r"\bretrospective(?:\s+cohort)?\b", "RETROSPECTIVE_COHORT"),
        ("prospective_cohort", "prospective_cohort", r"\bprospective\b[^.;]{0,50}\bobservational study\b|\bprospective cohort\b", "PROSPECTIVE_COHORT"),
        ("nonrandomized_interventional_study", "nonrandomized_interventional_study", r"\bobservational study\b", "OBSERVATIONAL"),
        ("pharmacokinetic_pharmacodynamic", "pharmacokinetic_pharmacodynamic", r"\b(?:pharmacokinetic(?:s)?|pharmacodynamic(?:s)?)\b", "PKPD"),
        ("mixed_human_preclinical", "mixed_human_preclinical", _MIXED_SCOPE.pattern, "MIXED_PRECLINICAL"),
        ("in_vitro", "in_vitro", r"\bin\s+vitro\b|\bcell line\b", "IN_VITRO"),
        ("animal_preclinical", "animal_preclinical", _PRECLINICAL.pattern, "ANIMAL"),
        ("narrative_review", "narrative_review", r"\bnarrative review\b|\breview\b", "NARRATIVE_REVIEW"),
        ("editorial_commentary_letter", "editorial_commentary_letter", r"\b(?:editorial|commentary|letter)\b", "EDITORIAL"),
    )
    for family, subtype, pattern, rule in checks:
        match = re.search(pattern, lower, re.I)
        if match:
            if rule == "PROTOCOL" and not _is_protocol_publication(value, source_type, match):
                continue
            if rule == "IN_VITRO" and not _is_in_vitro_study_context(value, match):
                continue
            if rule == "ANIMAL" and re.search(r"\b(?:in\s+vitro|cell\s+line)\b", match.group(0), re.I) and not _is_in_vitro_study_context(value, match):
                continue
            return _DesignSignal(family, subtype, source_type, field, match.group(0), f"TEXT_{rule}_{suffix}", _DESIGN_STRENGTH[source_type])
    return None


def _is_protocol_publication(value: str, source_type: str, match: re.Match[str]) -> bool:
    """Require publication/planning context, not protocol-adherence language."""
    if source_type == "title":
        return True
    context = value[max(0, match.start() - 80):match.end() + 160]
    return bool(re.search(
        r"\b(?:planned|future|propos(?:e|ed)|will\s+(?:be\s+assigned|enrol|enroll|randomi[sz]e)|aims?\s+to|"
        r"describes?\s+(?:a\s+)?planned|recruit(?:ment)?|enrollment)\b",
        context,
        re.I,
    ))


def _is_in_vitro_study_context(value: str, match: re.Match[str]) -> bool:
    """Keep mechanistic mentions from masquerading as the study design."""
    context = value[max(0, match.start() - 100):match.end() + 120]
    return bool(re.search(
        r"\b(?:methods?|experiment(?:s)?|assay(?:s)?|cell(?:s)?\s+(?:were\s+)?"
        r"(?:cultured|incubated|treated)|cultured|incubat(?:ed|ion)|performed)\b",
        context,
        re.I,
    ))


def _compatible_designs(left: str, right: str) -> bool:
    return left == right or {left, right} in (
        {"systematic_review_meta_analysis", "systematic_review_without_meta_analysis"},
        {"prospective_cohort", "nonrandomized_interventional_study"},
        {"protocol", "randomized_controlled_trial"},
    )


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
        return "mixed" if _MIXED_SCOPE.search(text) else "human"
    if pre:
        return "preclinical_only"
    if human:
        return "human"
    return "unclear"


def _result_status(article: Article, text: str, design_family: str) -> str:
    if not article.abstract and not article.abstract_sections:
        return "not_reported"
    if design_family == "protocol":
        if re.search(r"\b(?:we\s+)?propos(?:e|ed)\b|\bwill\s+(?:be\s+assigned|enrol|enroll|randomi[sz]e)\b", text, re.I):
            return "not_reported"
        if not re.search(r"\bresults?\b", text, re.I):
            return "not_reported"
    if article.abstract_sections and any(s.label.casefold() in {"results", "conclusions", "findings"} for s in article.abstract_sections):
        return "reported"
    return "reported" if _RESULTS.search(text) else "unclear"


def _sample_size(article: Article) -> tuple[int | None, str, list[SupportingSpan]]:
    text = _article_text(article)
    total_patterns = [
        ("total", rf"\b(?:retrospectively|prospectively)\s+analy[sz]ed\b[^.;]{{0,180}}\bin\s+{_NUMBER}\s+(?:(?:[A-Za-z-]+\s+){{0,6}})?(?:patients?|participants?|subjects?|individuals)\b"),
        ("total", rf"\b(?:a\s+)?total\s+of\s+{_NUMBER}\s+(?:(?:[A-Za-z-]+\s+){{0,3}})?(?:patients?|participants?|subjects?|children|adults|individuals|cases?|inpatients?)\s+(?:participated|were\s+(?:enrolled|randomi[sz]ed|included|divided))\b"),
        ("total", rf"\b(?:a\s+)?total\s+of\s+{_NUMBER}\b[^.;]{{0,60}}\bwere\s+randomi[sz]ed\b"),
        ("total", rf"\b{_NUMBER}\s+cases?\b[^.;]{{0,120}}\b(?:were\s+)?randomly\s+divided\b"),
        ("total", rf"\b{_NUMBER}\s+(?:inpatients?|patients?|participants?)\b[^.;]{{0,120}}\bwere\s+divided\b"),
        ("total", rf"\b{_NUMBER}\s+(?:patients?|participants?|subjects?|volunteers?)\s*\([^)]{{1,160}}\)\s+were\s+(?:enrolled|included|randomi[sz]ed)\b"),
        ("total", rf"\b(?:regimens?|treatments?|therapies|drugs?|agents?)(?:\s*,?\s*(?:and|or)\s+[A-Za-z-]+)*\s+were\s+administered\s+to\s+{_NUMBER}\s+(?:(?:healthy|adult|male|female)\s+){{0,4}}(?:participants?|subjects?|volunteers?)(?![^.;]{{0,40}}\b(?:each|per)\s+(?:arm|group)\b)"),
        ("total", rf"\bwere\s+administered\s+to\s+{_NUMBER}\s+(?:(?:healthy|adult|male|female)\s+){{0,4}}(?:participants?|subjects?|volunteers?)\s+during\s+(?:separate\s+)?(?:treatment\s+)?periods?\b"),
    ]
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
    secondary = _collect_population_counts(text, secondary_patterns)
    spans = [SupportingSpan("abstract", kind, snippet, rule) for kind, _, snippet, rule in secondary]
    totals = _collect_population_counts(text, total_patterns)
    totals = [item for item in totals if not re.search(r"\b(?:stud(?:y|ies)|trials?)\b", item[2], re.I)]
    if totals:
        value, snippet, rule = totals[0][1:]
        return value, "reported", [SupportingSpan("abstract", "sample_size", snippet, rule), *spans]
    primary = _collect_population_counts(text, primary_patterns)
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


def comparator_from_sentence(sentence: str) -> tuple[str, str] | None:
    """Return the primary clinical comparison from one eligible sentence."""
    if re.search(r"\b(?:pubmed|medline|embase|cochrane|search(?:ed| strategy)?|eligib(?:le|ility)|included\s+(?:trials?|studies)|cohort studies|publication dates?)\b", sentence, re.I):
        return None
    if not re.search(r"\b(?:patients?|participants?|subjects?|trial|randomi[sz]ed|assigned|allocated|received|treated|treatment)\b", sentence, re.I):
        return None
    if re.search(r"\b(?:previous|prior|published|literature|reports?|historical)\b", sentence, re.I):
        return None
    if re.search(r"\b(?:placebo )?run-in\b", sentence, re.I) and not re.search(r"\b(?:compared with|compared to|versus|vs\.?)\b", sentence, re.I):
        return None
    if (
        sentence.count("(") != sentence.count(")")
        or sentence.count("[") != sentence.count("]")
        or re.search(r"\b(?:compared\s+(?:with|to)|versus|vs\.?|and|or)\s*$", sentence, re.I)
    ):
        return None
    if re.search(r"\b\d+(?:\.\d+)?\s*(?:mg|g|mcg|Âµg)\b[^.;]{0,60}\b(?:versus|vs\.?)\s+\d+(?:\.\d+)?\s*(?:mg|g|mcg|Âµg)\b", sentence, re.I):
        return None
    if re.search(
        r"\bcompared\b[^.;]{0,80}\b(?:efficacy|safety)\b[^.;]{0,80}\bof\b"
        r"[^.;]{0,100}\b[A-Za-z][A-Za-z-]*\s+(?:\d+\s*[xÃ—]\s*)?\d+(?:\.\d+)?\s*(?:mg|g|mcg|Ã‚Âµg)\b"
        r"[^.;]{0,80}\band\b[^.;]{0,80}\b[A-Za-z][A-Za-z-]*\s+(?:\d+\s*[xÃ—]\s*)?\d+(?:\.\d+)?\s*(?:mg|g|mcg|Ã‚Âµg)\b",
        sentence,
        re.I,
    ):
        return "reported", sentence.strip()
    if re.search(r"\b(?:compared with|compared to|versus|vs\.?)\b", sentence, re.I):
        return "reported", sentence.strip()
    if re.search(r"\b(?:randomi[sz]ed|assigned|allocated)\b[^.;]{0,80}\b(?:to(?: receive)?|into|between)\b[^.;]{0,100}\b(?:and|or|either)\b[^.;]{1,80}", sentence, re.I):
        return "reported", sentence.strip()
    if re.search(r"\b(?:placebo|usual care|active comparator|no comparator)\b", sentence, re.I):
        return "not_applicable" if re.search(r"\bno comparator\b", sentence, re.I) else "reported", sentence.strip()
    return None


def _comparator(text: str) -> tuple[str, str | None, SupportingSpan | None]:
    for sentence in re.split(r"(?<=[.;])\s+", text):
        extracted = comparator_from_sentence(sentence)
        if not extracted:
            continue
        status, value = extracted
        return status, value, SupportingSpan("abstract", "comparator", value, "COMPARATOR_EXPLICIT")
    return "not_reported", None, None


def follow_up_from_text(text: str) -> str | None:
    """Return the canonical, context-anchored follow-up phrase from text."""
    duration = r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s*(?:days?|weeks?|months?|years?)"
    patterns = [
        rf"\bfollowed\s+(?:patients?|participants?|subjects?)\s+for\s+{duration}\b",
        rf"\bfollow(?:ed|[- ]up)?\s+(?:for|through|until)\s+{duration}\b",
        rf"\b(?:patients?|participants?|subjects?)\s+were\s+seen\s+and\s+assessed[^.;]{{0,180}}\bup\s+to\s+{duration}\b",
        rf"\b(?:seen\s+and\s+)?assessed\s+up\s+to\s+{duration}\b",
        rf"\brecurrence[^.;]{{0,80}}\bfollowed\s+up\s+for\s+{duration}\b",
        rf"\bevaluated\s+at\s+the\s+end\s+of\s+each\s+week\s+up\s+to\s+{duration}\b",
        rf"\bat\s+{duration}\s+follow[- ]up\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return match.group(0).strip()
    return None


def _follow_up(text: str) -> tuple[str | None, SupportingSpan | None]:
    value = follow_up_from_text(text)
    if value:
        return value, SupportingSpan("abstract", "follow_up", value, "FOLLOW_UP_EXPLICIT")
    return None, None


def _treatment_duration(text: str) -> tuple[str | None, SupportingSpan | None]:
    patterns = [
        r"\b(?:treated|receive|received|receiving|administered|dosed?|therapy)\b[^.;]{0,220}\bfor\s+\d+\s*(?:days?|weeks?|months?|years?)\b",
        r"\bcompared\s+with\s+[^.;]{0,120}\bfor\s+\d+\s*(?:days?|weeks?|months?|years?)\b",
        r"\bfor\s+\d+\s*(?:days?|weeks?|months?|years?)\s+of\s+treatment\b",
        r"\bdosing\s+for\s+\d+\s*(?:days?|weeks?|months?|years?)\b",
        r"\b(?:both|either|each)\b[^.;]{0,180}\bfor\s+\d+\s*(?:days?|weeks?|months?|years?)\b",
        r"\b(?:treatment|therapy)\s+(?:was\s+)?(?:continued|given|administered)\s+for\s+\d+\s*(?:days?|weeks?|months?|years?)\b",
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


def _limitations(article: Article, family: str, subtype: str, population: str, result_status: str, sample_status: str, comparator_status: str, follow_up: str | None, multicenter: str, tier: str, design_conflict: bool) -> list[str]:
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
    if design_conflict:
        values.append("conflicting_design_signals")
    if result_status == "unclear":
        values.append("methods_not_reported")
    if sample_status == "ambiguous":
        values.append("design_unclear")
    return list(dict.fromkeys(values))


def _reasons(family: str, subtype: str, tier: str, result_status: str, population: str, sample_status: str, comparator_status: str, limitations: list[str], design_conflict: bool) -> list[str]:
    reasons = [f"Design classified as {subtype} from prioritized PubMed metadata and explicit abstract signals.", f"Evidence tier {tier} is an abstract/metadata-based triage, not a formal quality assessment."]
    if result_status != "reported":
        reasons.append("Results were not sufficiently reported in the available abstract.")
    if population in {"preclinical_only", "mixed"}:
        reasons.append(f"Population scope is {population}; it is not silently treated as human clinical evidence.")
    if sample_status != "reported":
        reasons.append("Sample size was not assigned unless the text connected a number to a study population.")
    if comparator_status == "not_reported":
        reasons.append("Comparator was not reported in the available abstract.")
    if design_conflict:
        reasons.append("Credible design signals from equally reliable sources conflict; classification requires review.")
    return reasons


def _parse_int(value: str) -> int:
    return int(value.replace(",", ""))


def _collect_population_counts(text: str, patterns: list[tuple[str, str]]) -> list[tuple[str, int, str, str]]:
    items: list[tuple[str, int, str, str]] = []
    seen: set[tuple[str, int]] = set()
    for role, pattern in patterns:
        for match in re.finditer(pattern, text, re.I):
            value = _parse_int(match.group("n"))
            snippet = match.group(0)
            context = text[max(0, match.start() - 80):match.end() + 60]
            if _numeric_label_not_sample(text[max(0, match.start() - 24):match.end() + 32]):
                continue
            if role == "participants" and _is_event_count(context):
                continue
            if role in {"enrolled", "randomized", "included"} and re.search(r"\band\b.{0,20}\b(?:patients?|participants?|subjects?|children|adults|individuals|cases?)\b", snippet, re.I):
                continue
            key = (role, value)
            if key in seen or value == 0:
                continue
            seen.add(key)
            rule = {
                "enrolled": "SAMPLE_ENROLLED",
                "total": "SAMPLE_TOTAL",
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
            context = text[max(0, match.start() - 80):match.end() + 60]
            if _numeric_label_not_sample(text[max(0, match.start() - 24):match.end() + 32]):
                continue
            if role == "participants" and _is_event_count(context):
                continue
            if role in {"enrolled", "randomized", "included"} and re.search(r"\band\b.{0,20}\b(?:patients?|participants?|subjects?|children|adults|individuals|cases?)\b", snippet, re.I):
                continue
            key = (role, value)
            if key in seen or value == 0:
                continue
            seen.add(key)
            rule = {
                "enrolled": "SAMPLE_ENROLLED",
                "total": "SAMPLE_TOTAL",
                "randomized": "SAMPLE_RANDOMIZED",
                "included": "SAMPLE_INCLUDED",
                "participants": "SAMPLE_PARTICIPANT_COUNT",
                "completed": "SAMPLE_COMPLETED",
                "analyzed": "SAMPLE_ANALYZED",
                "pk_data": "SAMPLE_PK_DATA",
            }[role]
            items.append((role, value, snippet, rule))
    return items


def _is_event_count(context: str) -> bool:
    return bool(re.search(
        r"\b(?:occurred\s+in|events?\s+in|adverse\s+events?\s+in|"
        r"developed|experienced|had)\s+(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:patients?|participants?|subjects?|cases?)\b",
        context,
        re.I,
    ))


def _numeric_label_not_sample(snippet: str) -> bool:
    """Reject numeric arm/group labels and non-sample uses near population words."""
    return bool(re.search(
        r"\b(?:arm|group|site)\s+(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:patients?|participants?|subjects?|children|adults|individuals)\b"
        r"|\b\d+\s+cases?\s+in\s+each\s+group\b"
        r"|\b\d+\s+(?:patients?|participants?|subjects?|individuals)\s+(?:registry|database|records?)\b",
        snippet,
        re.I,
    ))


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
