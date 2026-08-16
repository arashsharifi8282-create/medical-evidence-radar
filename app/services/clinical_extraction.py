"""Conservative deterministic extraction from PubMed title and abstract."""
from __future__ import annotations
import re
from app.models.article import Article
from app.models.clinical import *


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
    text, section, rule = _first(article, [(r"\b(?:patients?|participants?|subjects?|volunteers?)\b[^.;]{0,180}", "POPULATION_DESCRIPTION")], preferred=("methods", "patients", "participants", "results", "findings", "abstract", "title"))
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
                if not re.search(r"\b(?:patients?|participants?|subjects?|trial|randomi[sz]ed|assigned|allocated|received|treated|treatment)\b", sentence, re.I):
                    continue
                match = re.search(r"\b(?:placebo|usual care|no treatment|historical control)\b", sentence, re.I)
                rule = "COMPARATOR_TYPE"
                if not match:
                    match = re.search(r"\b(?:compared with|compared to|versus|vs\.?)\s+((?!previous\b|prior\b|published\b|literature\b)[^.;,]{1,100})", sentence, re.I)
                    rule = "COMPARATOR_EXPLICIT"
                if not match:
                    continue
                value = match.group(0).strip()
                kind = "placebo" if re.search("placebo", value, re.I) else "usual_care" if re.search("usual care", value, re.I) else "no_treatment" if re.search("no treatment", value, re.I) else "active_comparator"
                return ComparatorExtraction(kind, value, (_prov(article,"comparator",section,value,rule),), "reported")
    return ComparatorExtraction()

def extract_outcomes(article: Article) -> tuple[OutcomeExtraction, ...]:
    out=[]
    for section, text in _parts(article):
        if section not in {"results", "findings", "conclusions", "abstract"}: continue
        for m in re.finditer(r"([^.;]{3,140}?)\b((?:RR|OR|HR|risk ratio|odds ratio|hazard ratio)\s*[=:]?\s*\d+(?:\.\d+)?|p\s*[<=>]\s*0?\.\d+|\d+(?:\.\d+)?%\s*(?:vs\.?|versus)\s*\d+(?:\.\d+)?%)", text, re.I):
            name, result = m.groups(); span=m.group(0).strip(); effect=re.search(r"\b(RR|OR|HR|risk ratio|odds ratio|hazard ratio)\b", result, re.I)
            sentence = text[max(0, m.start()-1):min(len(text), m.end()+80)]
            pval=re.search(r"\bp\s*[<=>]\s*0?\.\d+", sentence, re.I)
            out.append(OutcomeExtraction(name.strip(), "unspecified", effect_measure_type=effect.group(1).lower() if effect else None, effect_value=result if effect else None, p_value=pval.group(0) if pval else None, statistical_significance="reported" if pval else "unclear", provenance=(_prov(article,"outcome",section,span,"OUTCOME_RESULT"),)))
    return tuple(out[:12])

def extract_safety(article: Article) -> tuple[SafetyExtraction, ...]:
    text=" ".join(t for _,t in _parts(article)); out=[]
    if re.search(r"\bFAERS\b|disproportionality|reporting odds ratio|spontaneous reports", text, re.I):
        span=next((m.group(0) for m in re.finditer(r"[^.;]{0,100}(?:FAERS|disproportionality|reporting odds ratio|spontaneous reports)[^.;]{0,120}", text, re.I)), "pharmacovigilance signal")
        out.append(SafetyExtraction("reported adverse events", signal_source_type="disproportionality_signal", limitations=("reporting bias expected", "incidence cannot be calculated", "disproportionality does not establish causality"), provenance=(_prov(article,"safety", "results", span,"PHARMACOVIGILANCE_SIGNAL"),)))
    for m in re.finditer(r"([^.;]{0,80}(?:adverse events?|side effects?|toxicit(?:y|ies))[^.;]{0,100})", text, re.I):
        out.append(SafetyExtraction(m.group(0).strip(), signal_source_type="observed_event", provenance=(_prov(article,"safety","results",m.group(0).strip(),"ADVERSE_EVENT"),)))
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
        for sentence in _sentences(text):
            if re.search(r"\b(?:follow(?:ed|[- ]up)?|assessed|reviewed|visits?)\b", sentence, re.I) and re.search(r"\b\d+\s*(?:days?|weeks?|months?|years?)\b", sentence, re.I):
                return sentence.strip()
    return None
