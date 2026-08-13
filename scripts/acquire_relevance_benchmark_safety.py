"""Freeze a bounded PubMed safety pool for the B2.2A relevance benchmark.

This benchmark-only acquisition utility uses the existing PubMed client and writes
only the requested JSONL snapshot path.  It never invokes the production CLI or
changes production data/report locations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
import sys

# Make direct execution from the repository root resolve the local application.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.normalizer import normalize_article, parse_pubmed_articles
from app.sources.pubmed.client import PubMedClient


DEFAULT_QUERY = "semaglutide AND (safety OR adverse effects OR pharmacovigilance) AND obesity"


def article_dict(article) -> dict:
    """Serialize only metadata exposed by the normalized PubMed record."""
    return {
        "pmid": article.pmid,
        "title": article.title,
        "abstract": article.abstract,
        "authors": list(article.authors),
        "journal": article.journal,
        "publication_date": article.publication_date.isoformat() if article.publication_date else None,
        "publication_date_raw": article.publication_date_raw,
        "electronic_publication_date": (
            article.electronic_publication_date.isoformat() if article.electronic_publication_date else None
        ),
        "publication_types": list(article.publication_types),
        "doi": article.doi,
        "pubmed_url": article.pubmed_url,
        "mesh_descriptors": [
            {"text": item.text, "ui": item.ui, "major_topic": item.major_topic}
            for item in article.mesh_descriptors
        ],
        "keywords": list(article.keywords),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 50:
        parser.error("--limit must be between 1 and 50")

    client = PubMedClient()
    retrieved_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    search = client.search(args.query, retmax=args.limit)
    xml = client.efetch(search.pmids) if search.pmids else ""
    raw_sha256 = hashlib.sha256(xml.encode("utf-8")).hexdigest()
    by_pmid = {article.pmid: article for article in map(normalize_article, parse_pubmed_articles(xml))}
    records = []
    for rank, pmid in enumerate(search.pmids, start=1):
        if pmid not in by_pmid:
            continue
        records.append(
            {
                "topic_id": "semaglutide_obesity_safety",
                "retrieval_rank": rank,
                "retrieval_timestamp": retrieved_at,
                "source_snapshot_sha256": raw_sha256,
                "article": article_dict(by_pmid[pmid]),
                "prediction": {"current_b2_class": "not_run", "provenance": "not_run_for_benchmark"},
            }
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps({
        "query": args.query,
        "retrieval_timestamp": retrieved_at,
        "total_result_count": search.total_count,
        "pmid_order": list(search.pmids),
        "fetched_records": len(records),
        "source_snapshot_sha256": raw_sha256,
        "output": str(args.output),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())