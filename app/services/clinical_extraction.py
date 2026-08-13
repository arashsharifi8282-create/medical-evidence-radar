"""Conservative deterministic extraction from PubMed title and abstract."""
from __future__ import annotations
import re
from app.models.article import Article
from app.models.clinical import *

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
    text, section, rule = _first(article, [(r"\b(?:patients?|participants?|subjects?|volunteers?)\b[^.;]{0,140}", "POPULATION_DESCRIPTION")])
    scope = "human" if re.search(r"\b(?:patients?|participants?|humans?|volunteers?)\b", " ".join(x[1] for x in _parts(article)), re.I) else "preclinical_only" if re.search(r"\b(?:mice|mouse|rats?|animals?|in vitro|cell line)\b", article.abstract, re.I) else "unclear"
    special = tuple(x for x in ("children", "pregnan", "older adults", "elderly", "immunocompromised") if re.search(x, article.abstract, re.I))
    if not text: return PopulationExtraction(scope=scope)
    p = (_prov(article, "population", section, text, rule),)
    return PopulationExtraction(description=text, special_populations=special, scope=scope, provenance=p, status="reported")

def extract_interventions(article: Article) -> tuple[InterventionExtraction, ...]:
    found=[]
    pattern = r"\b([A-Za-z][A-Za-z-]{2,30})\b[^.;]{0,100}?\b(\d+(?:\.\d+)?)\s*(mg|g|mcg|µg|%)\b(?:\s+(oral|intravenous|intravenously|subcutaneous|topical))?[^.;]{0,50}?\b(once daily|twice daily|daily|weekly|per day)\b"
    for m in re.finditer(pattern, " ".join(t for _,t in _parts(article) if _ != "title"), re.I):
        name, value, unit, route, frequency = m.groups()
        span=m.group(0).strip(); found.append(InterventionExtraction(name, span, value, unit, route, frequency, None, None, None, (_prov(article,"intervention","methods",span,"INTERVENTION_DOSE"),), "reported"))
    if found: return tuple(found[:8])
    return (InterventionExtraction(status="not_reported"),)

def extract_comparator(article: Article) -> ComparatorExtraction:
    value, section, rule = _first(article, [(r"\b(placebo|usual care|no treatment|historical control)\b", "COMPARATOR_TYPE"),(r"\b(?:compared with|compared to|versus|vs\.?)\s+[^.;,]{1,80}", "COMPARATOR_EXPLICIT")])
    if not value: return ComparatorExtraction()
    kind = "placebo" if re.search("placebo", value, re.I) else "usual_care" if re.search("usual care", value, re.I) else "no_treatment" if re.search("no treatment", value, re.I) else "active_comparator"
    return ComparatorExtraction(kind, value, (_prov(article,"comparator",section,value,rule),), "reported")

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
    duration = next((x for x in (article.abstract, *(s.text for s in article.abstract_sections)) if re.search(r"\b(?:treated|therapy|dosing)\b[^.;]{0,100}\bfor\s+\d+\s*(?:days?|weeks?|months?)", x, re.I)), None)
    follow = next((x for x in (article.abstract, *(s.text for s in article.abstract_sections)) if re.search(r"\bfollow(?:ed|[- ]up)?[^.;]{0,80}\d+\s*(?:days?|weeks?|months?)", x, re.I)), None)
    conclusion = next((s.text for s in article.abstract_sections if s.label.casefold() in {"conclusions","conclusion"}), None)
    if conclusion is None and re.search(r"\b(?:in conclusion|we conclude)", article.abstract, re.I): conclusion=article.abstract
    missing=not bool(article.abstract or article.abstract_sections)
    warnings=("Full text review needed",) if missing else ()
    return ClinicalExtraction(article.pmid,pop,ints,comp,outs,safety,duration,follow,conclusion,confidence="low" if missing else "medium",needs_review=missing or pop.scope=="unclear",warnings=warnings)
