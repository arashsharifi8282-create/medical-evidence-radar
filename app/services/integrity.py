"""Conservative publication-integrity policy over structured PubMed metadata."""

from __future__ import annotations

from app.models.article import Article, PublicationIntegrityRelation
from app.models.integrity import PublicationIntegrityAssessment

RULE_ID = "PUBMED_PUBLICATION_INTEGRITY"
RULE_VERSION = "1.0"
SOURCE = "pubmed_structured_metadata"

_STATUS_PRECEDENCE = {
    "no_signal": 0,
    "corrected_or_updated": 1,
    "expression_of_concern": 2,
    "retracted": 3,
    "unknown": -1,
}

_RELATION_POLICY = {
    "retraction_in": ("retracted", "primary_article"),
    "retraction_of": ("retracted", "retraction_notice"),
    "expression_of_concern_in": ("expression_of_concern", "primary_article"),
    "expression_of_concern_for": ("expression_of_concern", "expression_of_concern_notice"),
    "erratum_in": ("corrected_or_updated", "primary_article"),
    "erratum_for": ("corrected_or_updated", "correction_notice"),
    "corrected_and_republished_in": ("corrected_or_updated", "primary_article"),
    "corrected_and_republished_from": ("corrected_or_updated", "primary_article"),
    "update_in": ("corrected_or_updated", "primary_article"),
    "update_of": ("corrected_or_updated", "other_integrity_notice"),
    "republished_in": ("corrected_or_updated", "primary_article"),
    "republished_from": ("corrected_or_updated", "primary_article"),
    "retracted_and_republished_in": ("retracted", "primary_article"),
    "retracted_and_republished_from": ("corrected_or_updated", "primary_article"),
}

_NON_INTEGRITY_RELATIONS = {
    "associated_dataset",
    "associated_publication",
    "comment_in",
    "comment_on",
    "summary_for_patients_in",
    "original_report_in",
    "reprint_in",
    "reprint_of",
    "cites",
}

_PUBLICATION_TYPE_POLICY = {
    "retracted publication": ("retracted", "primary_article"),
    "retraction of publication": ("retracted", "retraction_notice"),
    "expression of concern": ("expression_of_concern", "expression_of_concern_notice"),
    "published erratum": ("corrected_or_updated", "correction_notice"),
    "corrected and republished article": ("corrected_or_updated", "primary_article"),
}

_NOTICE_ROLES = {
    "correction_notice",
    "retraction_notice",
    "expression_of_concern_notice",
    "other_integrity_notice",
    "unknown",
}


def assess_publication_integrity(article: Article) -> PublicationIntegrityAssessment:
    """Assess one record without consulting title, abstract, or clinical data."""
    relations = tuple(sorted(article.integrity_relations, key=_relation_key))
    signals: list[tuple[str, str, str]] = []
    reason_codes: set[str] = set()
    unknown_relation = False
    incomplete_relation = False

    for relation in relations:
        if relation.normalized_relation in _NON_INTEGRITY_RELATIONS:
            continue
        policy = _RELATION_POLICY.get(relation.normalized_relation)
        if policy is None:
            unknown_relation = True
            reason_codes.add("UNKNOWN_REF_TYPE")
            signals.append(("unknown", "unknown", f"RefType:{relation.raw_ref_type or '<missing>'}"))
        else:
            status, role = policy
            signals.append((status, role, f"RefType:{relation.raw_ref_type}"))
        if not relation.related_pmid and not relation.related_doi:
            incomplete_relation = True
            reason_codes.add("INCOMPLETE_STRUCTURED_RELATION")

    for publication_type in article.publication_types:
        policy = _PUBLICATION_TYPE_POLICY.get(_normalized_label(publication_type))
        if policy:
            status, role = policy
            signals.append((status, role, f"PublicationType:{publication_type}"))

    if not signals:
        return PublicationIntegrityAssessment(
            status="no_signal",
            record_role="primary_article",
            needs_review=False,
            report_eligible=True,
            reason_codes=("NO_STRUCTURED_INTEGRITY_SIGNAL",),
            reason="No publication-integrity warning was found in the retained PubMed metadata.",
            supporting_signals=(),
            related_records=relations,
            rule_id=RULE_ID,
            rule_version=RULE_VERSION,
            source=SOURCE,
            final_decision="eligible_for_report",
        )

    known_statuses = {status for status, _, _ in signals if status != "unknown"}
    conflict = len(known_statuses) > 1
    if conflict:
        reason_codes.add("CONFLICTING_STRUCTURED_SIGNALS")
    status = max(known_statuses, key=lambda value: _STATUS_PRECEDENCE[value]) if known_statuses else "unknown"

    roles = {role for _, role, _ in signals}
    notice_roles = roles - {"primary_article", "unknown"}
    if unknown_relation or len(notice_roles) > 1:
        role = "unknown"
        if len(notice_roles) > 1:
            reason_codes.add("CONFLICTING_RECORD_ROLES")
    elif notice_roles:
        role = next(iter(notice_roles))
    else:
        role = "primary_article"

    if status == "retracted":
        reason_codes.add("RETRACTED_STRUCTURED_METADATA")
    elif status == "expression_of_concern":
        reason_codes.add("EXPRESSION_OF_CONCERN_STRUCTURED_METADATA")
    elif status == "corrected_or_updated":
        reason_codes.add("CORRECTION_OR_UPDATE_STRUCTURED_METADATA")
    else:
        reason_codes.add("UNRESOLVED_STRUCTURED_METADATA")

    needs_review = bool(
        unknown_relation
        or incomplete_relation
        or conflict
        or status in {"expression_of_concern", "unknown"}
    )
    report_eligible = status == "corrected_or_updated" and role == "primary_article"
    if status == "no_signal":
        report_eligible = True
    if status in {"retracted", "expression_of_concern", "unknown"} or role in _NOTICE_ROLES:
        report_eligible = False

    return PublicationIntegrityAssessment(
        status=status,
        record_role=role,
        needs_review=needs_review,
        report_eligible=report_eligible,
        reason_codes=tuple(sorted(reason_codes)),
        reason=_reason(status, role, needs_review),
        supporting_signals=tuple(sorted({signal for _, _, signal in signals})),
        related_records=relations,
        rule_id=RULE_ID,
        rule_version=RULE_VERSION,
        source=SOURCE,
        final_decision="eligible_for_report" if report_eligible else "excluded_integrity",
    )


def _reason(status: str, role: str, needs_review: bool) -> str:
    if role == "retraction_notice":
        return "PubMed structured metadata identifies this record as a retraction notice; it is retained for audit and excluded from clinical evidence."
    if role == "correction_notice":
        return "PubMed structured metadata identifies this record as a correction notice; no correction severity is inferred."
    if role == "expression_of_concern_notice":
        return "PubMed structured metadata identifies this record as an expression-of-concern notice requiring review."
    if status == "retracted":
        return "PubMed structured metadata identifies this article as retracted; its relevance assessment is retained but it is excluded from evidence reporting."
    if status == "expression_of_concern":
        return "PubMed structured metadata records an expression of concern; the record requires review and is excluded from ordinary evidence sections."
    if status == "corrected_or_updated":
        return "PubMed structured metadata records a correction, update, or republication; no severity is inferred."
    suffix = " Review is required." if needs_review else ""
    return "PubMed structured publication-integrity metadata could not be resolved." + suffix


def _relation_key(relation: PublicationIntegrityRelation) -> tuple[str, str, str, str, str]:
    return (
        relation.normalized_relation,
        relation.raw_ref_type,
        relation.related_pmid or "",
        relation.related_doi or "",
        relation.source_text,
    )


def _normalized_label(value: str) -> str:
    return " ".join(value.casefold().split())
