"""Conservative deterministic extraction from PubMed title and abstract."""
from __future__ import annotations
import re
from app.models.article import Article
from app.models.clinical import *
from app.services.study_design import comparator_from_sentence, follow_up_from_text


_DRUG_DOSE = re.compile(
    r"\b(?P<name>[A-Za-z][A-Za-z-]{2,30})\b\s*,?\s+"
    r"(?:(?P<count>\d+)\s*[x×]\s*)?(?P<dose>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>mg|g|mcg|µg|%)\b"
    r"(?:\s*\((?P<formulation>[^)]{1,60})\))?"
    r"(?:\s+(?P<route>oral|intravenous|intravenously|subcutaneous|topical))?"
    r"(?:\s+(?P<frequency>once daily|twice daily|daily|weekly|per day|five times daily|three times daily|TID))?",
    re.I,
)
_DOSE_REGIMEN = re.compile(
    r"\b(?P<dose>\d+(?:\.\d+)?)\s*(?P<unit>mg|g|mcg|µg|%)\b"
    r"(?:\s+(?P<frequency>once daily|twice daily|daily|weekly|per day|five times daily|three times daily|TID))?",
    re.I,
)
_THERAPY_REGIMEN_PAIR = re.compile(
    r"\b(?P<name>[A-Za-z][A-Za-z-]{2,30})\s+(?:therapy|treatment|regimen)\b"
    r"(?:\s+for\s+\d+\s*(?:days?|weeks?|months?|years?))?\s*,?\s*(?:either\s+)?"
    r"(?P<first>\d+(?:\.\d+)?\s*(?:mg|g|mcg|µg|%)(?:\s+(?:once daily|twice daily|daily|weekly|per day|five times daily|three times daily|TID))?)"
    r"\s+(?:versus|vs\.?|or|compared\s+with)\s+"
    r"(?P<second>\d+(?:\.\d+)?\s*(?:mg|g|mcg|µg|%)(?:\s+(?:once daily|twice daily|daily|weekly|per day|five times daily|three times daily|TID))?)",
    re.I,
)
_CONTROL_INTERVENTION_WORDS = frozenset({
    "versus", "vs", "either", "or", "and", "compared", "group", "arm", "treatment",
    "patients", "participants", "subjects", "received", "randomly", "oral", "the", "with",
    "from", "study",
})
_POPULATION_NOUNS = r"inpatients?|outpatients?|patients?|participants?|subjects?|volunteers?|children|adults|individuals?"
_POPULATION_HEAD = re.compile(
    rf"\b(?P<head>(?:(?:\d[\d,]*|[A-Za-z][A-Za-z-]*)\s+){{0,6}}(?:{_POPULATION_NOUNS}))\b",
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
    for wanted in ("methods", "patients", "participants", "results", "findings", "abstract", "title"):
        for candidate_section, candidate_text in _parts(article):
            if candidate_section != wanted and not (wanted == "methods" and re.search(r"\bmethods\b", candidate_section)):
                continue
            candidate = _population_description(candidate_text)
            if candidate:
                text, section, rule = candidate, candidate_section, "POPULATION_ENROLLMENT"
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


def _population_description(text: str) -> str | None:
    best = None
    for sentence in _sentences(text):
        if re.search(r"\b(?:primary|secondary)\s+(?:endpoints?|outcomes?)\b|\bproportion of patients\b|\bstudy protocol\b|\b(?:particularly|especially) (?:for|in) patients\b|\bpatients?\b[^.;]{0,100}\bmay (?:benefit|require)\b|\bwill be (?:recruited|enrolled|randomi[sz]ed|allocated)\b", sentence, re.I):
            continue
        for match in _POPULATION_HEAD.finditer(sentence):
            head = re.sub(r"^(?:(?:in|of|while|the|a|an)\s+)+", "", match.group("head"), flags=re.I).strip()
            head = re.sub(r"^(?:(?:[IVX]+)\s+)?trial\s+in\s+", "", head, flags=re.I)
            counts = list(re.finditer(r"\d[\d,]*", head))
            if counts:
                head = head[counts[-1].start():]
            if re.search(r"\bof\s+(?:these|the)\b", head, re.I):
                continue
            noun = re.search(rf"\b(?:{_POPULATION_NOUNS})\b$", head, re.I)
            if not noun:
                continue
            prefix = head[:noun.start()].strip()
            qualifiers = [word for word in re.findall(r"[A-Za-z][A-Za-z-]*", prefix.casefold()) if word not in {"a", "an", "and", "in", "of", "one", "or", "the", "to", "two", "three", "with"}]
            remainder = sentence[match.end():]
            has_count = bool(re.search(r"\d", head))
            has_enrollment = bool(re.search(r"\b(?:enrolled|included|participated|assigned|treated|studied|analy[sz]ed|received|divided)\b|\b(?:were|was)\s+randomi[sz]ed\b|\bwho\s+will\s+be\s+assigned\b", remainder, re.I))
            has_detail = bool(re.match(r"\s+(?:aged\b|with\b|who\b|enrolled\s+in\b)", remainder, re.I))
            unsafe_detail = bool(re.search(r"\b(?:toxicity|adverse|outcome|improved|response)\b|\bp\s*=|\d+\.\d+", remainder, re.I))
            has_study_context = bool(re.search(r"\b(?:study|trial|randomi[sz]ed|compared|comparison)\b", sentence[:match.start()], re.I))
            specific_noun = noun.group(0).casefold() in {"children", "adults", "volunteer", "volunteers"}
            if has_count and not (has_enrollment or (has_detail and not unsafe_detail) or has_study_context):
                continue
            if has_detail and unsafe_detail:
                continue
            if not (has_count or qualifiers or has_detail or specific_noun):
                continue
            if not (has_count or has_enrollment or has_detail) and not re.search(r"\b(?:with|aged|who|from|undergoing|after)\b", remainder, re.I):
                continue
            description = _extend_population_description(head, remainder)
            if not _safe_population_description(description):
                continue
            score = 3 * has_enrollment + 3 * has_count + 2 * has_detail + bool(qualifiers) + bool(specific_noun) + has_study_context
            candidate = (score, -len(description), description)
            if best is None or candidate > best:
                best = candidate
    return best[2] if best else None


def _safe_population_description(value: str) -> bool:
    """Reject incomplete parser spans while retaining complete enrollment clauses."""
    if value.count("(") != value.count(")") or value.count("[") != value.count("]"):
        return False
    if re.search(r"\b(?:vs\.?|versus|and|or|received|randomi[sz]ed)\s*$", value, re.I):
        return False
    if re.match(r"\s*(?:most|some|more|fewer)\s+(?:patients?|participants?|subjects?)\b", value, re.I):
        return False
    if re.search(r":\s*(?:A|An|The)\s+(?:Randomi[sz]ed|Controlled|Prospective|Retrospective)\s*$", value, re.I):
        return False
    return True


def _extend_population_description(head: str, remainder: str) -> str:
    description = head
    tail = remainder
    detail = re.match(r"\s+(?:aged\s+|with\s+)(?P<value>[^.;,]*?)(?=\s+(?:(?:were|was)\s+)?(?:enrolled|included|randomi[sz]ed|assigned|treated|studied|analy[sz]ed|received|divided)\b|[.;,]|$)", tail, re.I)
    if detail:
        description = f"{description} {detail.group(0).strip()}"
        tail = tail[detail.end():]
    enrolled_in = re.match(r"\s+enrolled\s+in\s+(?P<value>[^.;,]*?)(?=\s+(?:were|was)\b|[.;,]|$)", tail, re.I)
    if enrolled_in:
        return f"{description} {enrolled_in.group(0).strip()}"
    action = re.match(r"\s+(?:(?:were|was)\s+)?(?P<action>enrolled|included|participated|randomi[sz]ed|assigned|treated|studied|analy[sz]ed|received|divided)\b", tail, re.I)
    if action and re.fullmatch(r"randomi[sz]ed", action.group("action"), re.I):
        return description
    return f"{description} {action.group(0).strip()}" if action else description

def extract_interventions(article: Article) -> tuple[InterventionExtraction, ...]:
    found=[]
    seen = set()
    for section, section_text in _content_parts(article):
        for sentence in _sentences(section_text):
            for match in _DRUG_DOSE.finditer(sentence):
                name = match.group("name")
                if not _supported_intervention_name(name):
                    continue
                _append_intervention(found, seen, article, section, name, match.group(0).strip(), match.group("dose"), match.group("unit"), match.group("route"), match.group("frequency"), match.group("formulation"))
                linked = re.match(r"\s*(?:versus|vs\.?|or|compared\s+with)\s+(?P<regimen>.+)$", sentence[match.end():], re.I)
                if linked:
                    regimen = _DOSE_REGIMEN.match(linked.group("regimen"))
                    if regimen:
                        span = f"{name} {regimen.group(0).strip()}"
                        _append_intervention(found, seen, article, section, name, span, regimen.group("dose"), regimen.group("unit"), None, regimen.group("frequency"), None, provenance_span=match.group(0).strip())
            for match in _THERAPY_REGIMEN_PAIR.finditer(sentence):
                name = match.group("name")
                if not _supported_intervention_name(name):
                    continue
                for regimen_name in ("first", "second"):
                    regimen = _DOSE_REGIMEN.fullmatch(match.group(regimen_name))
                    if regimen:
                        span = f"{name} {regimen.group(0).strip()}"
                        _append_intervention(found, seen, article, section, name, span, regimen.group("dose"), regimen.group("unit"), None, regimen.group("frequency"), None)
    if found: return tuple(found[:8])
    return (InterventionExtraction(status="not_reported"),)


def _supported_intervention_name(name: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z][A-Za-z-]{2,30}", name or "")) and name.casefold() not in _CONTROL_INTERVENTION_WORDS


def _append_intervention(found, seen, article, section, name, span, dose, unit, route, frequency, formulation, provenance_span=None):
    key = (name.casefold(), dose, unit.casefold() if unit else None, route, frequency, formulation)
    if key in seen:
        return
    seen.add(key)
    found.append(InterventionExtraction(name, span, dose, unit, route, frequency, _duration_from_sentence(span), formulation, None, (_prov(article,"intervention",section,provenance_span or span,"INTERVENTION_DOSE"),), "reported"))

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
                leading = re.match(r"\s*(?:for|regarding)\s+(?P<name>[A-Za-z][A-Za-z -]{1,60}?)(?:,|\s+there\b)", sentence, re.I)
                post_effect = re.search(r"\bfor\s+(?:the\s+)?(?:treatment|prevention)\s+of\s+(?P<name>[A-Za-z][A-Za-z -]{1,60}?)(?=\s+(?:among|in)\b|[.;]|$)", sentence[effect.end():], re.I)
                candidate = (leading or post_effect)
                name = candidate.group("name").strip() if candidate else None
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
    if cleaned.count("(") != cleaned.count(")") or cleaned.count("[") != cleaned.count("]"):
        return None
    if re.search(r"\b(?:score|ratio|rate|risk)\s+of$", cleaned, re.I):
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
            if re.search(r"\b(?:secondary outcomes? included|were (?:collected|assessed)|data were (?:also )?collected|review assessed|conducted a systematic review|search(?:ed| strategy)?|eligib(?:le|ility)|database|methods?|study compared (?:adverse event|ae) profiles?|have been linked to adverse events?|comparison of adverse events?)\b", sentence, re.I):
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
