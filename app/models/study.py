"""Typed, conservative study-design and evidence-strength assessment models."""

from __future__ import annotations

from dataclasses import dataclass


TriState = str


@dataclass(frozen=True)
class SupportingSpan:
    """A source-backed signal used by the B3 rules."""

    field: str
    source_type: str
    text: str
    rule_id: str


@dataclass(frozen=True)
class StudyAssessment:
    """Abstract/metadata-based evidence-strength triage for one article."""

    design_family: str
    design_subtype: str
    population_scope: str
    result_status: str
    evidence_tier: str
    confidence: str
    needs_review: bool
    sample_size: int | None
    sample_size_status: str
    comparator_status: str
    comparator_text: str | None
    randomized: TriState
    blinded: TriState
    prospective: TriState
    retrospective: TriState
    multicenter: TriState
    follow_up_text: str | None
    data_source_type: str
    limitation_codes: tuple[str, ...]
    matched_signals: tuple[str, ...]
    supporting_spans: tuple[SupportingSpan, ...]
    assessment_reasons: tuple[str, ...]
    rule_version: str
