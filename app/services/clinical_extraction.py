"""Conservative deterministic extraction from PubMed title and abstract."""
from __future__ import annotations
import re
from app.models.article import Article
from app.models.clinical import *
from app.services.study_design import comparator_from_sentence, follow_up_from_text


_DRUG_DOSE = re.compile(
    r"\b(?P<name>[A-Za-z][A-Za-z-]{2,30})\b\s+"
    r"(?:(?P<count>\d+)\s*[x×]\s*)?(?P<dose>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>mg|g|mcg|µg|%)\b"
    r"(?:\s*\((?P<formulation>[^)]{1,60})\))?"
    r"(?:\s+(?P<route>oral|intravenous|intravenously|subcutaneous|topical))?"
    r"(?:\s+(?P<frequency>once daily|twice daily|daily|weekly|per day|five times daily|three times daily))?",
    re.I,
)
_MIXED_POPULATION = re.compile(r"\b(?:patients?|participants?|humans?)\b\s+(?:and|with|alongside|as\s+well\s+as)\s+\b(?:mice|mouse|rats?|animals?|preclinical|in\s+vitro|cell\s+line)\b|\b(?:mice|mouse|rats?|animals?|preclinical|in\s+vitro|cell\s+line)\b\s+(?:and|with|alongside|as\s+well\s+as)\s+\b(?:patients?|participants?|humans?)\b", re.I)


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text or "") if part.strip()]


def _content_parts(article: Article) -> list[tuple[str, str]]:
    """Return sections while keeping background out of treatment fields."""
    parts = _parts(article)
    preferred = [(section, text) for section, text in parts if section in {"methods", "patients", "participants", "results", "findings"}]
    return preferred or parts

def _parts(article: Article) -> list[tuple[str, str]]:
    labelled = [(s.label.casefold() or "abstract", s.text) for s in article.abstract_sections]
    return [("title", article.title), *(labelled or [("abstract", article.abstract)])]

def _prov(article, field, section, span, rule, confidence="medium", status="reported", review=False, ambiguity=None):
    return ExtractionProvenance(article.pmid, field, section, span, rule, confidence, ambiguity, review, status)

def _first(article, patterns, preferred=("methods", "results", "conclusions", "title", "abstract")):
    for wanted in preferred:
        for section, text in _parts(article):
            if section != wanted: continue
            for pattern, rule in patterns:
                m = re.search(pattern, text, re.I)
                if m: return m.group(0).strip(), section, rule
    return None, None, None

def extract_population(article: Article) -> PopulationExtraction:
    text = section = rule = None
    population_pattern = re.compile(
        r"\b(?:(?:[A-Za-z-]+)\s+){0,5}(?:patients?|participants?|subjects?|volunteers?|children|adults)\b"
        r"[^.;]{0,160}\b(?:were\s+)?(?:enrolled|included|randomi[sz]ed|assigned|treated|studied|analy[sz]ed|received)\b",
        re.I,
    )
    for wanted in ("methods", "patients", "participants", "results", "findings", "abstract", "title"):
        for candidate_section, candidate_text in _parts(article):
            if candidate_section != wanted:
                continue
            match = population_pattern.search(candidate_text)
            if match:
                text, section, rule = match.group(0).strip(), candidate_section, "POPULATION_ENROLLMENT"
                break
        if text:
            break
    primary = " ".join(text for _, text in _content_parts(article))
    human = bool(re.search(r"\b(?:patients?|participants?|humans?|volunteers?|children|adults)\b", primary, re.I))
    preclinical = bool(re.search(r"\b(?:mice|mouse|rats?|animals?|preclinical|in vitro|cell line)\b", primary, re.I))
    scope = "mixed_human_preclinical" if human and preclinical and _MIXED_POPULATION.search(primary) else "human" if human else "preclinical_only" if preclinical else "unclear"
    special = tuple(x for x in ("children", "pregnancy", "older adults", "elderly", "immunocompromised") if re.search(x, primary, re.I))
    if not text: return PopulationExtraction(scope=scope)
    p = (_prov(article, "population", section, text, rule),)
    return PopulationExtraction(description=text, special_populations=special, scope=scope, provenance=p, status="reported")

def extract_interventions(article: Article) -> tuple[InterventionExtraction, ...]:
    found=[]
    text = " ".join(t for _, t in _content_parts(article))
    for m in _DRUG_DOSE.finditer(text):
        name = m.group("name")
        if name.casefold() in {"patients", "participants", "subjects", "received", "randomly", "oral", "the", "and", "with", "from", "study", "group"}:
            continue
        span=m.group(0).strip()
        duration = _duration_from_sentence(span)
        found.append(InterventionExtraction(name, span, m.group("dose"), m.group("unit"), m.group("route"), m.group("frequency"), duration, m.group("formulation"), None, (_prov(article,"intervention","methods",span,"INTERVENTION_DOSE"),), "reported"))
    if found: return tuple(found[:8])
    return (InterventionExtraction(status="not_reported"),)

def extract_comparator(article: Article) -> ComparatorExtraction:
    for wanted in ("methods", "patients", "participants", "results", "findings", "abstract"):
        for section, text in _parts(article):
            if section != wanted:
                continue
            for sentence in _sentences(text):
                extracted = comparator_from_sentence(sentence)
                if not extracted:
                    continue
                _, value = extracted
                rule = "COMPARATOR_EXPLICIT"
                kind = "placebo" if re.search("placebo", value, re.I) else "usual_care" if re.search("usual care", value, re.I) else "no_treatment" if re.search("no treatment", value, re.I) else "active_comparator"
                return ComparatorExtraction(kind, value, (_prov(article,"comparator",section,value,rule),), "reported")
    return ComparatorExtraction()

def extract_outcomes(article: Article) -> tuple[OutcomeExtraction, ...]:
    out=[]
    for section, text in _parts(article):
        if section not in {"results", "findings", "conclusions", "abstract"}: continue
        for sentence in _sentences(text):
            effect = re.search(r"\b(?:OR|RR|HR)\b\s*(?:[=:]\s*|\s+)\d+(?:\.\d+)?|(?i:\b(?:odds|risk|hazard) ratio\b)\s*(?:[=:]\s*|\s+)\d+(?:\.\d+)?", sentence)
            if not effect:
                continue
            name = _safe_outcome_name(sentence[:effect.start()])
            if not name:
                continue
            span = sentence.strip()
            label = re.search(r"\b(?:OR|RR|HR)\b|(?i:\b(?:odds|risk|hazard) ratio\b)", effect.group(0))
            pval=re.search(r"\bp\s*[<=>]\s*0?\.\d+", sentence, re.I)
            out.append(OutcomeExtraction(name, "unspecified", effect_measure_type=label.group(0).lower() if label else None, effect_value=effect.group(0), p_value=pval.group(0) if pval else None, statistical_significance="reported" if pval else "unclear", provenance=(_prov(article,"outcome",section,span,"OUTCOME_RESULT"),)))
    return tuple(out[:12])


def _safe_outcome_name(value: str) -> str | None:
    cleaned = re.sub(r"^\s*(?:results?|findings?)\s*:\s*", "", value, flags=re.I).strip(" \t,;:()[]")
    if not cleaned or not re.search(r"[A-Za-z]", cleaned):
        return None
    if re.search(r"\b(?:p\s*[<=>]|results?\s+(?:was|were)|result\s+was)\b", cleaned, re.I):
        return None
    if re.search(r"(?:^|\s)(?:or|and)\s*\d+(?:\.\d+)?\s*(?:mg|g|mcg)\b", cleaned, re.I):
        return None
    lexical = re.findall(r"[A-Za-z][A-Za-z-]*", cleaned)
    if len(lexical) < 2:
        return None
    return cleaned

def extract_safety(article: Article) -> tuple[SafetyExtraction, ...]:
    text=" ".join(t for _,t in _parts(article)); out=[]
    if re.search(r"\bFAERS\b|disproportionality|reporting odds ratio|spontaneous reports", text, re.I):
        span=next((m.group(0) for m in re.finditer(r"[^.;]{0,100}(?:FAERS|disproportionality|reporting odds ratio|spontaneous reports)[^.;]{0,120}", text, re.I)), "pharmacovigilance signal")
        out.append(SafetyExtraction("reported adverse events", signal_source_type="disproportionality_signal", limitations=("reporting bias expected", "incidence cannot be calculated", "disproportionality does not establish causality"), provenance=(_prov(article,"safety", "results", span,"PHARMACOVIGILANCE_SIGNAL"),)))
    for section, section_text in _content_parts(article):
        for sentence in _sentences(section_text):
            if not re.search(r"\b(?:adverse events?|side effects?|toxicit(?:y|ies)|nausea|emesis)\b", sentence, re.I):
                continue
            value = sentence.strip()
            out.append(SafetyExtraction(value, signal_source_type="observed_event", provenance=(_prov(article,"safety",section,value,"ADVERSE_EVENT"),)))
    return tuple(out[:12])

def extract_clinical(article: Article) -> ClinicalExtraction:
    pop=extract_population(article); ints=extract_interventions(article); comp=extract_comparator(article); outs=extract_outcomes(article); safety=extract_safety(article)
    duration = _first_duration(article)
    follow = _first_follow_up(article)
    conclusion = next((s.text for s in article.abstract_sections if s.label.casefold() in {"conclusions","conclusion"}), None)
    if conclusion is None and re.search(r"\b(?:in conclusion|we conclude)", article.abstract, re.I): conclusion=article.abstract
    missing=not bool(article.abstract or article.abstract_sections)
    warnings=("Full text review needed",) if missing else ()
    return ClinicalExtraction(article.pmid,pop,ints,comp,outs,safety,duration,follow,conclusion,confidence="low" if missing else "medium",needs_review=missing or pop.scope=="unclear",warnings=warnings)


def _duration_from_sentence(text: str) -> str | None:
    match = re.search(r"\bfor\s+\d+\s*(?:days?|weeks?|months?|years?)\b", text or "", re.I)
    return match.group(0) if match else None


def _first_duration(article: Article) -> str | None:
    for section, text in _content_parts(article):
        for sentence in _sentences(text):
            if re.search(r"\b(?:treated|received|administered|dosed?|therapy|treatment|compared|versus|vs\.?)\b", sentence, re.I) and _duration_from_sentence(sentence):
                return sentence.strip()
    return None


def _first_follow_up(article: Article) -> str | None:
    for section, text in _content_parts(article):
        value = follow_up_from_text(text)
        if value:
            return value
    return None
