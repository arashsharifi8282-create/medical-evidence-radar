"""Typed publication-integrity assessment models for Phase B5."""

from dataclasses import dataclass

from app.models.article import PublicationIntegrityRelation


@dataclass(frozen=True)
class PublicationIntegrityAssessment:
    """A deterministic assessment based only on retained PubMed metadata."""

    status: str
    record_role: str
    needs_review: bool
    report_eligible: bool
    reason_codes: tuple[str, ...]
    reason: str
    supporting_signals: tuple[str, ...]
    related_records: tuple[PublicationIntegrityRelation, ...]
    rule_id: str
    rule_version: str
    source: str
    final_decision: str
