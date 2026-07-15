"""
Automated DPDP data-handling check, run once per document right after
upload/extraction — mirrors the frontend's mock implementation
(src/data/mockDocuments.ts:checkDpdpCompliance) exactly, since the project
doc's blocking rule ("no real records enter the pipeline until data-handling
terms exist with the buyer") is a pod-wide policy, not a UI-only detail.

Filename-pattern matching is intentionally the entire check for this POC:
there's no real Waqf-board provenance/consent system to inspect yet, and
the pitch treats "synthetic-only, DPDP-by-design" as a feature (see project
doc, Section 7 risks). Segment 4 (admin) is the natural place to make this
configurable once real data-handling terms exist.
"""
from __future__ import annotations

import re

from app.models import DpdpStatus

_SYNTHETIC_FILENAME_RE = re.compile(r"(synthetic|sample|demo|template|test)", re.IGNORECASE)


def check_dpdp_compliance(filename: str) -> tuple[DpdpStatus, str]:
    if _SYNTHETIC_FILENAME_RE.search(filename or ""):
        return (
            DpdpStatus.compliant,
            "Filename matches the synthetic/sample naming convention — no DPDP data-handling terms required.",
        )
    return (
        DpdpStatus.needs_review,
        "Could not confirm this is a synthetic/de-identified sample. No DPDP data-handling terms exist with "
        "the buyer yet — a supervisor must verify provenance before this record proceeds.",
    )
