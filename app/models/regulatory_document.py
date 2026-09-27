"""FDA-specific immutable application observations, independent of PubMed Article."""
from dataclasses import dataclass


@dataclass(frozen=True)
class RegulatoryDocument:
    source_document_id: str
    sponsor_name: str | None
    document_status: str
    content_digest: str
    products: tuple[dict, ...]
    submissions: tuple[dict, ...]


@dataclass(frozen=True)
class RegulatoryObservation:
    method: str
    scope: str | None
    dataset_timestamp: str | None
    records: tuple[RegulatoryDocument, ...]