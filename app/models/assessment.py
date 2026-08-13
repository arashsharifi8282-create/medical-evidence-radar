"""Evidence assessment data model for ranked articles."""

from dataclasses import dataclass

from app.models.article import Article
from app.models.relevance import ClinicalRelevanceAssessment
from app.models.study import StudyAssessment

# Evidence level — a closed set of 6 categories.
EvidenceLevel = str
# Values: "guideline", "systematic_review", "randomized_trial",
#         "observational", "narrative_review", "other"

# Report section — 3 categories.
EvidenceSection = str
# Values: "key_evidence", "important_updates", "exploratory_evidence"


@dataclass(frozen=True)
class EvidenceAssessment:
    """A transparent, rule-based assessment of a single article."""

    evidence_level: EvidenceLevel
    evidence_level_label: str
    relevance_score: int
    evidence_score: int
    overall_score: int
    is_future_issue_dated: bool
    is_electronic_only: bool
    has_abstract: bool
    abstract_status: str
    reasons: tuple[str, ...]
    limitations: tuple[str, ...]
    section: EvidenceSection
    study_assessment: StudyAssessment | None = None


@dataclass(frozen=True)
class RankedArticle:
    """An article paired with its evidence assessment."""

    article: Article
    assessment: EvidenceAssessment
    clinical_relevance: ClinicalRelevanceAssessment | None = None
