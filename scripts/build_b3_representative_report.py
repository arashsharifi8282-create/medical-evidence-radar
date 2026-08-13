"""Build the offline Phase B3 representative report from frozen local data."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from app.models.article import AbstractSection, Article, MeshDescriptor
from app.services.evidence import rank_articles
from app.services.normalizer import normalize_article, parse_pubmed_articles
from app.services.persistence import build_html_report, build_markdown_report, build_snapshot

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "b3_representative"
FIXTURE = ROOT / "tests" / "fixtures" / "efetch_sample.xml"
FROZEN = ROOT / "tests" / "fixtures" / "relevance_b2_2b" / "real_frozen_batch_01_articles.jsonl"
PMIDS = {
    "38521990",  # human RCT
    "42584177",  # systematic review/meta-analysis
    "40858452",  # observational human study
    "42376629",  # case series
    "40342468",  # pharmacovigilance signal
    "42262870",  # preclinical-only
    "37142308",  # protocol
    "42556356",  # unknown/insufficient metadata
}


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _article(row: dict) -> Article:
    descriptors = tuple(
        MeshDescriptor(
            text=item.get("text", ""),
            ui=item.get("ui", ""),
            major_topic=bool(item.get("major_topic", False)),
            supporting_pmid=item.get("supporting_pmid", row.get("pmid", "")),
        )
        for item in row.get("mesh_descriptors", [])
    )
    sections = tuple(
        AbstractSection(item.get("label", ""), item.get("text", ""))
        for item in row.get("abstract_sections", [])
    )
    return Article(
        pmid=row.get("pmid", ""),
        title=row.get("title", ""),
        abstract=row.get("abstract", ""),
        authors=tuple(row.get("authors", [])),
        journal=row.get("journal", ""),
        publication_date=_date(row.get("publication_date")),
        publication_date_raw=row.get("publication_date_raw", ""),
        electronic_publication_date=_date(row.get("electronic_publication_date")),
        is_epub_ahead_of_print=bool(row.get("is_epub_ahead_of_print", False)),
        publication_types=tuple(row.get("publication_types", [])),
        doi=row.get("doi", ""),
        pubmed_url=row.get("pubmed_url", ""),
        source=row.get("source", "pubmed"),
        mesh_headings=tuple(row.get("mesh_headings", [])),
        keywords=tuple(row.get("keywords", [])),
        mesh_descriptors=descriptors,
        abstract_sections=sections,
    )


def _load_local_articles() -> dict[str, Article]:
    articles = {item.pmid: item for item in (normalize_article(elem) for elem in parse_pubmed_articles(FIXTURE.read_text(encoding="utf-8")))}
    for line in FROZEN.read_text(encoding="utf-8").splitlines():
        item = json.loads(line)["article"]
        articles[item["pmid"]] = _article(item)
    for path in sorted((ROOT / "data" / "raw").rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for item in payload.get("articles", []):
            if item.get("pmid") in PMIDS:
                articles.setdefault(item["pmid"], _article(item))
    missing = sorted(PMIDS - articles.keys())
    if missing:
        raise RuntimeError(f"Missing frozen representative PMIDs: {missing}")
    return articles


def main() -> None:
    articles = _load_local_articles()
    fetched_at = datetime(2026, 8, 13, 12, 0, 0)
    ranked = rank_articles([articles[pmid] for pmid in sorted(PMIDS)], fetched_at, topic="human clinical evidence")
    visible = [item for item in ranked if item.assessment.study_assessment and item.assessment.study_assessment.population_scope != "preclinical_only"]
    snapshot = build_snapshot(
        topic="B3 representative frozen evidence-strength triage",
        query="offline frozen representative set",
        fetched_at=fetched_at,
        ranked=ranked,
    )
    snapshot["schema_version"] = "b3-representative"
    snapshot["assessment_scope"] = "Abstract/metadata-based evidence-strength triage"
    snapshot["assessment_notice"] = "Not full-text appraisal, GRADE, formal risk-of-bias assessment, or a clinical recommendation."
    snapshot["visible_article_pmids"] = [item.article.pmid for item in visible]
    snapshot["audit_only_pmids"] = [item.article.pmid for item in ranked if item not in visible]
    snapshot["representative_groups"] = {
        "human_rct": "38521990",
        "systematic_review_meta_analysis": "42584177",
        "observational_human": "40858452",
        "case_series": "42376629",
        "pharmacovigilance": "40342468",
        "preclinical_only_audit": "42262870",
        "protocol": "37142308",
        "unknown_metadata": "42556356",
    }
    markdown = build_markdown_report(
        "B3 representative frozen evidence-strength triage",
        fetched_at,
        ranked=visible,
    )
    html = build_html_report(
        "B3 representative frozen evidence-strength triage",
        fetched_at,
        ranked=visible,
    )
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "representative.json").write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (OUT / "representative.md").write_text(markdown, encoding="utf-8")
    (OUT / "representative.html").write_text(html, encoding="utf-8")
    print(json.dumps({"all": len(ranked), "visible": len(visible), "audit_only": snapshot["audit_only_pmids"], "designs": {item.article.pmid: item.assessment.study_assessment.design_family for item in ranked}}, indent=2))


if __name__ == "__main__":
    main()
