"""Freeze one bounded PubMed class-level pool for B2.2A benchmark enrichment.

This benchmark-only utility preserves the frozen query verbatim, uses one ESearch
and batched EFetch requests, and writes only the requested JSONL snapshot. It
does not invoke or alter the production application.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.normalizer import normalize_article, parse_pubmed_articles
from app.sources.pubmed.client import PubMedClient


FROZEN_QUERY = (
    '("Angiotensin II Type 1 Receptor Blockers"[MeSH Terms] OR '
    '"Angiotensin Receptor Antagonists"[MeSH Terms] OR '
    '"angiotensin receptor blocker"[Title/Abstract] OR '
    '"angiotensin receptor blockers"[Title/Abstract] OR '
    '"angiotensin II receptor antagonist"[Title/Abstract] OR '
    '"angiotensin II receptor antagonists"[Title/Abstract]) AND '
    '("Hypertension"[MeSH Terms] OR hypertension[Title/Abstract])'
)


def article_dict(article) -> dict:
    """Serialize only title/abstract-level metadata supplied by PubMed."""
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


def fetch_batched(client: PubMedClient, pmids: tuple[str, ...], batch_size: int) -> list[str]:
    """Fetch ordered IDs in bounded batches; retry a failed batch at most once."""
    xml_parts = []
    for start in range(0, len(pmids), batch_size):
        batch = list(pmids[start : start + batch_size])
        try:
            xml_parts.append(client.efetch(batch))
        except Exception:
            xml_parts.append(client.efetch(batch))
    return xml_parts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--batch-size", type=int, default=20)
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 40:
        parser.error("--limit must be between 1 and 40")
    if not 1 <= args.batch_size <= 40:
        parser.error("--batch-size must be between 1 and 40")

    client = PubMedClient()
    retrieved_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    search = client.search(FROZEN_QUERY, retmax=args.limit)
    xml_batches = fetch_batched(client, search.pmids, args.batch_size) if search.pmids else []
    source_sha256 = hashlib.sha256("\n".join(xml_batches).encode("utf-8")).hexdigest()
    by_pmid = {
        article.pmid: article
        for xml in xml_batches
        for article in map(normalize_article, parse_pubmed_articles(xml))
    }
    records = []
    for rank, pmid in enumerate(search.pmids, start=1):
        article = by_pmid.get(pmid)
        if article is None:
            continue
        records.append(
            {
                "topic_id": "losartan_hypertension",
                "retrieval_rank": rank,
                "retrieval_timestamp": retrieved_at,
                "source_snapshot_sha256": source_sha256,
                "article": article_dict(article),
                "prediction": {"current_b2_class": "not_run", "provenance": "not_run_for_benchmark"},
            }
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "query": FROZEN_QUERY,
                "retrieval_timestamp": retrieved_at,
                "total_result_count": search.total_count,
                "pmid_order": list(search.pmids),
                "fetched_records": len(records),
                "source_snapshot_sha256": source_sha256,
                "output": str(args.output),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())