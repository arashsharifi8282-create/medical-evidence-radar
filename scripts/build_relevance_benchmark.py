"""Build the frozen, source-grounded B2.2A benchmark pilot (no production imports)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "benchmarks" / "relevance_b2_2a"
LOSARTAN = ROOT / "data/raw/pubmed/losartan_efficacy_and_safety_in_hypertension_20260811_105332.json"
MASLD = ROOT / "data/raw/pubmed/masldtitle_abstract_or_mashtitle_abstract_or_metabolic_dysfunction_associated_steatohepatitistitle_abstract_b26293137106.json"
SAFETY = OUT / "safety_candidate_pool.jsonl"

MASLD_IDS = ["42323099","42559181","42264075","42242572","42213742","42571423","42456707","42348222","42338042","42285006","40549581","42215136","42575231","42558980","42552573","42545725","42541628","42538551","42538483","42454754","42446260","42438128","42395062","42387868","42273973","42233597","42229581","42139907","42127430","42009939","41895606","42421259","42527732","42526426","42517548","42577170"]
SAFETY_IDS = ["42584177","42410329","42403263","42382663","42376629","42575111","42572056","42262870","42567173","42562129","42560457","42558052","42547656","42339050","42323166","42321502","42309121","42286992","42256775","42252120","42251859","42225305","42208070","42165084"]

TOPICS = [
 {"topic_id":"losartan_hypertension","frozen_query":"losartan efficacy and safety in hypertension","explicit_interventions":["losartan"],"intervention_logic":"OR","explicit_conditions":["hypertension"],"intent":"efficacy_and_safety","candidate_pool_source":"data/raw/pubmed/losartan_efficacy_and_safety_in_hypertension_20260811_105332.json","sampling_quota":24,"retrieval_timestamp":"2026-08-11T07:23:32Z","target_normalization_provenance":{"intervention_rxcui":"52175","source":"existing B2.1 audit artifact"},"limitation":"Only 10 locally frozen candidates were available; target quota shortfall is intentional."},
 {"topic_id":"masld_mash_multi_intervention","frozen_query":"(MASLD[Title/Abstract] OR MASH[Title/Abstract] OR metabolic dysfunction-associated steatohepatitis[Title/Abstract]) AND (resmetirom[Title/Abstract] OR semaglutide[Title/Abstract] OR tirzepatide[Title/Abstract] OR survodutide[Title/Abstract] OR efruxifermin[Title/Abstract] OR pegozafermin[Title/Abstract] OR lanifibranor[Title/Abstract] OR denifanstat[Title/Abstract] OR FGF21[Title/Abstract] OR thyroid hormone receptor beta[Title/Abstract] OR pan-PPAR[Title/Abstract] OR de novo lipogenesis[Title/Abstract])","explicit_interventions":["resmetirom","semaglutide","tirzepatide","survodutide","efruxifermin","pegozafermin","lanifibranor","denifanstat","FGF21","thyroid hormone receptor beta","pan-PPAR","de novo lipogenesis"],"intervention_logic":"OR","explicit_conditions":["MASLD","MASH","metabolic dysfunction-associated steatohepatitis"],"intent":"emerging_pharmacotherapy","candidate_pool_source":"data/raw/pubmed/masldtitle_abstract_or_mashtitle_abstract_or_metabolic_dysfunction_associated_steatohepatitistitle_abstract_b26293137106.json","sampling_quota":36,"retrieval_timestamp":"2026-08-11T10:51:00Z","target_normalization_provenance":{"source":"existing B2.1 audit artifact","note":"Historical query is preserved verbatim; complete intervention OR set is not collapsed."}},
 {"topic_id":"semaglutide_obesity_safety","frozen_query":"semaglutide AND (safety OR adverse effects OR pharmacovigilance) AND obesity","explicit_interventions":["semaglutide"],"intervention_logic":"OR","explicit_conditions":["obesity"],"intent":"safety_pharmacovigilance","candidate_pool_source":"benchmarks/relevance_b2_2a/safety_candidate_pool.jsonl","sampling_quota":24,"retrieval_timestamp":"2026-08-12T23:52:08Z","target_normalization_provenance":{"source":"not run; benchmark acquisition only","status":"unknown"},"total_result_count":1178},
]

def sha(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()
def load(path: Path): return json.loads(path.read_text(encoding="utf-8"))
def write_json(path: Path, value): path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)+"\n",encoding="utf-8")

def relevance(topic, article):
    text=(article.get("title","")+" "+article.get("abstract","")).casefold()
    if topic=="losartan_hypertension":
        if article["pmid"]=="40274695": return "direct",["losartan"],["hypertension"],["DIRECT_TARGET_FOCUS"]
        if article["pmid"]=="42570044": return "contextual",["losartan"],["hypertension"],["BROAD_MULTI_INTERVENTION_REVIEW"]
        if article["pmid"]=="40342468": return "needs",["losartan"],["hypertension"],["AMBIGUOUS_FROM_AVAILABLE_METADATA"]
        return "irrelevant",[],["hypertension"] if "hypertension" in text else [],["MISSING_INTERVENTION"]
    if topic=="masld_mash_multi_intervention":
        names=[n for n in TOPICS[1]["explicit_interventions"] if n.casefold() in text]
        condition=["MASH"] if ("mash" in text or "steatohepatitis" in text or "masld" in text) else []
        if article["pmid"] in {"42456707","42348222","42545725","42273973","41895606","42527732","42517548"}: return "direct",names,condition,["DIRECT_TARGET_FOCUS"]
        if article["pmid"] in {"42395062","42421259","42552573","42233597","42438128"}: return "contextual",names,condition,["BROAD_MULTI_INTERVENTION_REVIEW"]
        if article["pmid"] in {"42571423","42213742","42139907","42009939"}: return "needs",names,condition,["AMBIGUOUS_FROM_AVAILABLE_METADATA"]
        if "animal" in text or "rat" in text: return "irrelevant",names,condition,["PRECLINICAL_HUMAN_MISMATCH"]
        return "irrelevant",names,condition,["OTHER_INTERVENTION_PRIMARY_FOCUS"]
    names=["semaglutide"] if "semaglutide" in text else []
    condition=["obesity"] if "obesity" in text or "overweight" in text else []
    if article["pmid"] in {"42410329","42403263","42575111","42560457","42558052"}: return "direct",names,condition,["DIRECT_TARGET_FOCUS"]
    if article["pmid"] in {"42584177","42382663","42376629","42262870","42547656"}: return "needs",names,condition,["AMBIGUOUS_FROM_AVAILABLE_METADATA"]
    if article["pmid"] in {"42572056","42562129","42567173"}: return "contextual",names,condition,["OTHER_INTERVENTION_PRIMARY_FOCUS"]
    return "irrelevant",names,condition,["MISSING_INTERVENTION"] if not names else ["MISSING_CONDITION"]

def record(topic, rank, article, source_sha, timestamp, prediction):
    return {"schema_version":"1.0","benchmark_id":"relevance_b2_2a","topic_id":topic,"retrieval_rank":rank,"retrieval_timestamp":timestamp,"source_snapshot_sha256":source_sha,"article":article,"prediction":prediction}

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    los=load(LOSARTAN); mas=load(MASLD)
    safety=[json.loads(line) for line in SAFETY.read_text(encoding="utf-8").splitlines()]
    collections=[("losartan_hypertension",los["articles"],None,los["fetched_at"],sha(LOSARTAN)),("masld_mash_multi_intervention",[a for a in mas["articles"] if a["pmid"] in MASLD_IDS],MASLD_IDS,mas["fetched_at"],sha(MASLD)),("semaglutide_obesity_safety",[r["article"] for r in safety if r["article"]["pmid"] in SAFETY_IDS],SAFETY_IDS,"2026-08-12T23:52:08Z",safety[0]["source_snapshot_sha256"])]
    rows=[]; labels=[]
    for topic, articles, wanted, timestamp, source_sha in collections:
        if wanted: articles=sorted(articles,key=lambda a:wanted.index(a["pmid"]))
        for rank,a in enumerate(articles,1):
            cr=a.get("clinical_relevance") or {}
            pred={"current_b2_class":cr.get("relevance_class","not_run"),"visible_in_default_output":cr.get("decision","").startswith("included_"),"visible_section":a.get("assessment",{}).get("section") if a.get("assessment") else "unknown","ranking_score":a.get("assessment",{}).get("overall_score") if a.get("assessment") else None,"matched_interventions":[],"provenance":"existing audit artifact" if cr else "not_run_for_benchmark"}
            rows.append(record(topic,rank,a,source_sha,timestamp,pred))
            klass,mi,mc,codes=relevance(topic,a)
            status="needs_review" if klass=="needs" else "draft"
            labels.append({"schema_version":"1.0","benchmark_id":"relevance_b2_2a","topic_id":topic,"pmid":a["pmid"],"query":next(t["frozen_query"] for t in TOPICS if t["topic_id"]==topic),"target_interventions":next(t["explicit_interventions"] for t in TOPICS if t["topic_id"]==topic),"intervention_logic":next(t["intervention_logic"] for t in TOPICS if t["topic_id"]==topic),"target_conditions":next(t["explicit_conditions"] for t in TOPICS if t["topic_id"]==topic),"gold_relevance_class":None if status=="needs_review" else klass,"matched_interventions":mi,"matched_conditions":mc,"article_focus":"unknown" if status=="needs_review" else ("target" if klass=="direct" else "contextual_or_other"),"coherence_status":"unknown" if status=="needs_review" else ("coherent" if klass=="direct" else "not_sufficient"),"reason_codes":codes,"human_or_preclinical":"unknown","within_class_priority":"not_assessed","reviewer":"benchmark_seed_reviewer","second_reviewer":None,"adjudication_notes":"Source-grounded provisional label from title/abstract/metadata only; not an adjudicated gold label.","label_status":status,"source_snapshot_sha256":source_sha})
    with (OUT/"articles.jsonl").open("w",encoding="utf-8",newline="\n") as f:
        for x in rows:f.write(json.dumps(x,ensure_ascii=False,sort_keys=True)+"\n")
    with (OUT/"draft_labels.jsonl").open("w",encoding="utf-8",newline="\n") as f:
        for x in labels:f.write(json.dumps(x,ensure_ascii=False,sort_keys=True)+"\n")
    (OUT/"adjudicated_labels.jsonl").write_text("",encoding="utf-8")
    write_json(OUT/"topics.json",{"schema_version":"1.0","benchmark_id":"relevance_b2_2a","topics":TOPICS})
    print(f"wrote {len(rows)} articles and {len(labels)} provisional labels")
if __name__=="__main__":main()