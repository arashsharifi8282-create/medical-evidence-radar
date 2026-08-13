"""B4 structured, source-grounded clinical extraction models."""

from dataclasses import dataclass, field

EXTRACTION_STATUSES = {"reported", "not_reported", "unclear", "conflicting", "not_applicable", "not_extractable"}

@dataclass(frozen=True)
class ExtractionProvenance:
    article_pmid: str
    field: str
    source_section: str
    supporting_span: str
    rule_id: str
    confidence: str = "medium"
    ambiguity: str | None = None
    review_required: bool = False
    status: str = "reported"

@dataclass(frozen=True)
class PopulationExtraction:
    description: str | None = None
    condition: str | None = None
    age_or_range: str | None = None
    sex_distribution: str | None = None
    special_populations: tuple[str, ...] = ()
    setting: str | None = None
    region: str | None = None
    scope: str = "unclear"
    provenance: tuple[ExtractionProvenance, ...] = ()
    status: str = "not_reported"

@dataclass(frozen=True)
class InterventionExtraction:
    normalized_name: str | None = None
    source_text: str | None = None
    dose_value: str | None = None
    dose_unit: str | None = None
    route: str | None = None
    frequency: str | None = None
    treatment_duration: str | None = None
    formulation: str | None = None
    arm_label: str | None = None
    provenance: tuple[ExtractionProvenance, ...] = ()
    status: str = "not_reported"

@dataclass(frozen=True)
class ComparatorExtraction:
    kind: str = "not_reported"
    source_text: str | None = None
    provenance: tuple[ExtractionProvenance, ...] = ()
    status: str = "not_reported"

@dataclass(frozen=True)
class OutcomeExtraction:
    name: str
    status: str = "unspecified"
    time_point: str | None = None
    measurement_scale: str | None = None
    intervention_result: str | None = None
    comparator_result: str | None = None
    effect_measure_type: str | None = None
    effect_value: str | None = None
    confidence_interval: str | None = None
    p_value: str | None = None
    direction: str | None = None
    statistical_significance: str = "unclear"
    clinical_significance: str = "not_reported"
    category: str = "efficacy"
    provenance: tuple[ExtractionProvenance, ...] = ()

@dataclass(frozen=True)
class SafetyExtraction:
    event_name: str
    serious_status: str = "unclear"
    arm_result: str | None = None
    withdrawal_result: str | None = None
    author_attributed_relationship: str | None = None
    signal_source_type: str = "observed_event"
    limitations: tuple[str, ...] = ()
    provenance: tuple[ExtractionProvenance, ...] = ()

@dataclass(frozen=True)
class ClinicalExtraction:
    pmid: str
    population: PopulationExtraction
    interventions: tuple[InterventionExtraction, ...]
    comparator: ComparatorExtraction
    outcomes: tuple[OutcomeExtraction, ...]
    safety_findings: tuple[SafetyExtraction, ...]
    treatment_duration: str | None
    follow_up: str | None
    authors_conclusion: str | None
    provenance: tuple[ExtractionProvenance, ...] = ()
    confidence: str = "medium"
    needs_review: bool = False
    warnings: tuple[str, ...] = ()

@dataclass(frozen=True)
class ReportPlacement:
    section: str
    primary_role: str
    visible: bool
    reason: str
    components: dict = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
