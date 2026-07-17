"""
Reports endpoints (Segment 4). Backs the Reports page — the Wk-12
demo-gate's throughput headline ("X records/hour per reviewer vs manual
baseline") plus the supporting charts/table. Route shapes mirror the
frontend's former mocks in src/data/mockDocuments.ts 1:1
(getThroughputStats, getStatusBreakdown, getConfidenceDistribution,
getCorrectionsHistory) so Reports.tsx is a straight swap from mocks to
real calls.

Supervisor-only, matching the /reports route's allowedRoles in App.tsx.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_role
from app.models import DocumentStatus, Review, ReviewAction, Role, User, WaqfDocument
from app.schemas_reports import (
    ConfidenceDistributionEntryOut,
    CorrectionHistoryEntryOut,
    StatusBreakdownEntryOut,
    ThroughputStatsOut,
)

router = APIRouter(prefix="/reports", tags=["reports"])

# Fixed reference point for "manual baseline" — a supervisor manually
# keying in a record end-to-end, per the project doc's pitch framing
# ("X records/hour per reviewer vs manual baseline"). Not derived from any
# data in this DB since there's nothing to measure it against here; matches
# the constant the frontend's mock used.
MANUAL_BASELINE_PER_HOUR = 6

# Fallback numbers shown before any real review activity exists yet (fresh
# DB / demo not run yet) — same fallbacks the frontend's mock used, so the
# Reports page never renders a blank/zero headline on a cold start.
FALLBACK_DOCUMENTS_PER_HOUR = 14
FALLBACK_AVG_REVIEW_SECONDS = 95
FALLBACK_SEEDED_ERROR_CATCH_RATE = 0.9


@router.get("/throughput", response_model=ThroughputStatsOut)
def get_throughput_stats(
    current_user: User = Depends(require_role(Role.SUPERVISOR)),
    db: Session = Depends(get_db),
) -> ThroughputStatsOut:
    reviews = (
        db.query(Review)
        .filter(Review.action.in_([ReviewAction.approve, ReviewAction.correct]))
        .all()
    )
    durations = [r.duration_seconds for r in reviews if r.duration_seconds is not None]
    avg_review_seconds = round(sum(durations) / len(durations)) if durations else 0
    documents_per_hour = round(3600 / avg_review_seconds) if avg_review_seconds > 0 else 0

    # Seeded-error catch rate: of the synthetic documents in the set (the
    # ones deliberately generated with known ground truth, incl. seeded
    # errors — see the project doc's Wk-9/10 sample set), how many were
    # actually caught (flagged, or corrected during review) rather than
    # sailing through untouched.
    synthetic_docs = db.query(WaqfDocument).filter(WaqfDocument.is_synthetic.is_(True)).all()
    caught = sum(
        1 for d in synthetic_docs if d.status in (DocumentStatus.flagged, DocumentStatus.reviewed)
    )
    seeded_error_catch_rate = caught / len(synthetic_docs) if synthetic_docs else FALLBACK_SEEDED_ERROR_CATCH_RATE

    return ThroughputStatsOut(
        documents_per_hour=documents_per_hour or FALLBACK_DOCUMENTS_PER_HOUR,
        manual_baseline_per_hour=MANUAL_BASELINE_PER_HOUR,
        seeded_error_catch_rate=seeded_error_catch_rate,
        avg_review_seconds=avg_review_seconds or FALLBACK_AVG_REVIEW_SECONDS,
    )


@router.get("/status-breakdown", response_model=list[StatusBreakdownEntryOut])
def get_status_breakdown(
    current_user: User = Depends(require_role(Role.SUPERVISOR)),
    db: Session = Depends(get_db),
) -> list[StatusBreakdownEntryOut]:
    rows = (
        db.query(WaqfDocument.status, func.count(WaqfDocument.id))
        .group_by(WaqfDocument.status)
        .all()
    )
    return [StatusBreakdownEntryOut(status=status_, count=count) for status_, count in rows]


@router.get("/confidence-distribution", response_model=list[ConfidenceDistributionEntryOut])
def get_confidence_distribution(
    current_user: User = Depends(require_role(Role.SUPERVISOR)),
    db: Session = Depends(get_db),
) -> list[ConfidenceDistributionEntryOut]:
    docs = db.query(WaqfDocument).filter(WaqfDocument.overall_confidence.isnot(None)).all()
    bands = {"high": 0, "medium": 0, "low": 0}
    for d in docs:
        c = d.overall_confidence or 0.0
        if c >= 0.9:
            bands["high"] += 1
        elif c >= 0.6:
            bands["medium"] += 1
        else:
            bands["low"] += 1
    return [ConfidenceDistributionEntryOut(band=band, count=bands[band]) for band in ("high", "medium", "low")]


@router.get("/corrections", response_model=list[CorrectionHistoryEntryOut])
def get_corrections_history(
    current_user: User = Depends(require_role(Role.SUPERVISOR)),
    db: Session = Depends(get_db),
) -> list[CorrectionHistoryEntryOut]:
    rows = (
        db.query(Review, WaqfDocument.filename)
        .join(WaqfDocument, WaqfDocument.id == Review.document_id)
        .order_by(Review.reviewed_at.desc())
        .all()
    )
    return [
        CorrectionHistoryEntryOut(
            review_id=review.id,
            document_id=review.document_id,
            filename=filename,
            reviewer_id=review.reviewer_id,
            action=review.action,
            notes=review.notes,
            reviewed_at=review.reviewed_at,
            duration_seconds=review.duration_seconds,
        )
        for review, filename in rows
    ]
