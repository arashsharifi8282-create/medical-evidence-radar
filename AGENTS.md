# Medical Evidence Radar — Agent Guidance

## Purpose and safety boundary

This project retrieves, normalizes, assesses, and presents medical-literature evidence. It is a research-support tool, not clinical decision support or medical advice. Preserve uncertainty, provenance, and auditability; do not imply diagnosis, treatment recommendations, or regulatory approval.

## Engineering principles

- Keep behavior deterministic, source-linked, explainable, and auditable.
- Inspect `git status` and relevant diffs before editing. Preserve user changes and never revert unrelated work.
- Never invent citations, clinical relationships, identifiers, evidence claims, or missing metadata. Do not silently infer a relationship from co-occurrence alone.
- Keep **relevance** (intervention/condition/intent fit) distinct from **evidence quality** (study design and ranking).
- Use structured abstracts and explicit signals. Relevance decisions account for query intent, article focus, condition coherence, population scope, content role, and needs-review reasons. Co-occurrence alone is insufficient.
- Pilot reviewer data supports regression/replay work only; it is not official gold-standard adjudication.

## Current checkpoint and architecture

Completed local checkpoint: **Phase B2.2B.2**.

- `app/sources/pubmed/`: PubMed retrieval, CLI orchestration, normalization inputs.
- `app/sources/rxnorm/`: RxNorm lookup and RxClass provenance retrieval.
- `app/models/`: normalized article, relevance, retrieval, and assessment models.
- `app/services/normalizer.py`: source normalization and structured abstracts.
- `app/services/relevance.py`: deterministic target construction, relevance assessment, and ranking selection.
- `app/services/persistence.py`: JSON, Markdown, and HTML audit/report serialization.
- `tests/`: offline regression, client, persistence, and relevance coverage.

Canonical validation command:

```powershell
.\.venv\Scripts\python.exe -m pytest -ra -W default
```

## Clinical-target and class provenance

Class-level relevance requires an approved structural RxClass relationship with explicit provenance. Current accepted sources are ATC and MEDRT; structural relations are `has_member`, `isa`, or `part_of`. Do not manufacture class relationships or promote mechanism/indication relations.

Live RxNorm resolves losartan and semaglutide, but the live builder currently returns no approved structural RxClass relation for either. Therefore the engine supports class-level evidence but it is unavailable for those two live targets. MeSH is **not** a production class authority; adding it requires separate explicit approval and a provenance/schema decision.

## Scope and repository hygiene

- Do not add an LLM, MedCPT, database, guidelines, web app, Docker, email, deployment, or other later-phase work without explicit approval.
- Do not commit or push unless explicitly authorized. When authorized, stage explicit paths only—never `git add .`, `git add -A`, or broad wildcards.
- Generated `data/` and `reports/` artifacts (including raw PubMed snapshots, caches, concepts, and topic profiles) should not be staged by default. Treat them as local audit outputs unless explicitly requested.