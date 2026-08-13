"""Versioned B4 policy and deterministic report placement."""
from __future__ import annotations
import json
from pathlib import Path
from app.models.assessment import RankedArticle

POLICY_PATH = Path(__file__).resolve().parents[2] / "config" / "report_policy.json"
def load_policy(path: Path = POLICY_PATH) -> dict:
    data=json.loads(path.read_text(encoding="utf-8"))
    required={"policy_id","schema_version","policy_version","defaults","rules"}
    missing=required-set(data)
    if missing: raise ValueError(f"policy missing required fields: {sorted(missing)}")
    if data["defaults"].get("principal_article_limit", 0) < 1: raise ValueError("principal article limit must be positive")
    return data

def route_report_section(item: RankedArticle, human_clinical_query: bool = True) -> tuple[str,bool,str]:
    relevance=item.clinical_relevance; study=item.assessment.study_assessment
    if study and human_clinical_query and study.population_scope == "preclinical_only": return "audit_only",False,"Preclinical-only evidence is excluded from an implicit human clinical report."
    role=relevance.content_role if relevance else "clinical_evidence"
    family=study.design_family if study else "unknown"
    if family in {"case_report","case_series"}: return "early_safety_signals",True,"Drug-specific case evidence is routed as a limited safety signal."
    if family == "pharmacovigilance_disproportionality": return "pharmacovigilance_signals",True,"Pharmacovigilance evidence is a non-causal signal with reporting bias and no incidence estimate."
    if role in {"emerging_mechanism","research_enabler"}: return "emerging_mechanisms_and_research_trends",True,"Mechanism or research-enabling content is contextual, not direct treatment evidence."
    if family == "narrative_review": return "clinical_background_and_overview",True,"Narrative review is limited overview evidence."
    if relevance and relevance.relevance_class in {"direct","class_level"}:
        if study and study.sample_size is not None and study.sample_size < 30:
            return "clinical_background_and_overview",True,"Small studies remain relevant but are not principal evidence by default."
        intents = set(relevance.query_intents)
        if "efficacy" in intents and "safety" not in intents and study and study.comparator_status == "not_reported":
            return "clinical_background_and_overview",True,"Comparative efficacy requires a reported comparator."
        return "key_evidence",True,"Eligible direct or provenance-backed class-level clinical evidence."
    if relevance and relevance.relevance_class == "contextual": return "clinical_background_and_overview",True,"Contextual evidence retained separately from principal evidence."
    return "audit_only",False,"Does not satisfy the active clinical relevance criteria."
