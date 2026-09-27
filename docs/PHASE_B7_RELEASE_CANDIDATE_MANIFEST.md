# Phase B7 — Release-candidate file manifest and dry-run staging plan

**Status: release manifest for B7 v0.7.0.** This document inventories the
explicit release paths. It does not itself stage, commit, tag, push, or
publish anything; remote publication is verified separately. The second
independent acceptance review concluded **ACCEPTED — READY FOR RELEASE
PREPARATION**.

## Proposed release-candidate paths

Stage only the following explicit paths after a separate authorization and
after reviewing each path's staged diff:

```text
.gitignore
AGENTS.md
README.md
app/models/regulatory_document.py
app/services/regulatory_normalizer.py
app/services/regulatory_persistence.py
app/sources/regulatory/__init__.py
app/sources/regulatory/cli.py
app/sources/regulatory/fda_openfda.py
app/sources/regulatory/validation.py
docs/PHASE_B7_D6_ATTESTATION_CONTRACT.md
docs/PHASE_B7_M0_SOURCE_CONTRACT.md
docs/PHASE_B7_PROPOSED.md
docs/PHASE_B7_RELEASE_CANDIDATE_MANIFEST.md
docs/PHASE_B7_RESEARCH_PACKAGE.md
docs/PHASE_B7_RTM.md
docs/PROJECT_FUTURE_ROADMAP.md
scripts/run_b7_d6_attestation.py
tests/fixtures/b7_regulatory/adversarial_expectations.json
tests/fixtures/b7_regulatory/bulk_manifest.json
tests/fixtures/b7_regulatory/bulk_partition.json.zip
tests/fixtures/b7_regulatory/expected.json
tests/fixtures/b7_regulatory/manifest.json
tests/fixtures/b7_regulatory/query_response.json
tests/test_b7_adapter.py
tests/test_b7_d6_attestation.py
tests/test_b7_regulatory.py
```

`AGENTS.md` and `README.md` were inspected and are included in this release
manifest because the B7 release-status language required amendment
(second-review acceptance, v0.7.0 release state). `.gitattributes` already
protects checksummed fixtures and needs no change. `docs/PROJECT_FUTURE_ROADMAP.md`
is included because its stale B7/D6 status wording was corrected while retaining
its untracked history.

## Must remain local and unstaged

- `data/regulatory/` D6 data, reports, completion markers, and attestations;
- environment variables, API credentials, shell history, and personal
  configuration (`opencode.json`, `opencode.jsonc`);
- existing unrelated modified/untracked `data/concepts/` and
  `data/topic_profiles/` files;
- `PROJECT_DOCUMENTATION.md` and any other unrelated untracked documents; and
- all generated `reports/` content.

The dry-run staging command, for a separately authorized future release
candidate, must name the paths above explicitly. Do not use `git add .`,
`git add -A`, or wildcards. Before any staging action, run
`git check-ignore -v data/regulatory/<dedicated-run>/<file>` and confirm that
the local generated paths are ignored; then inspect `git diff --cached --check`
and `git diff --cached --name-only`.

## Scope check

The manifest excludes B5/B6 production paths, generated regulatory output,
EMA/WHO/NICE work, PDF retrieval, B7 pairwise comparison, B8 work, unrelated
concept/topic-profile files, and local editor configuration.