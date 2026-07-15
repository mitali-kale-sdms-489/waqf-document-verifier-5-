"""
Schemas for Segment 4 reports endpoints. Shapes mirror the frontend's
former mocks in src/data/mockDocuments.ts (AuditThroughputStats,
StatusBreakdownEntry, ConfidenceDistributionEntry, CorrectionHistoryEntry)
1:1 so Reports.tsx is a straight swap from mocks to real calls.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from app.models import DocumentStatus, ReviewAction


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


class ThroughputStatsOut(CamelModel):
    """Matches AuditThroughputStats in src/types/domain.ts. This is the
    Wk-12 demo-gate headline number ("X records/hour per reviewer vs
    manual baseline")."""

    documents_per_hour: int
    manual_baseline_per_hour: int
    seeded_error_catch_rate: float  # e.g. 18/20 -> 0.9
    avg_review_seconds: int


class StatusBreakdownEntryOut(CamelModel):
    status: DocumentStatus
    count: int


class ConfidenceDistributionEntryOut(CamelModel):
    band: str  # "high" | "medium" | "low"
    count: int


class CorrectionHistoryEntryOut(CamelModel):
    review_id: str
    document_id: str
    filename: str
    reviewer_id: str
    action: ReviewAction
    notes: str | None
    reviewed_at: datetime
    duration_seconds: int | None
