"""
Segment 3 — validation-rule engine.

Runs the four rules named in the project doc (mandatory-field completeness,
survey number format, date sanity/plausibility, cross-document consistency)
against a document's *current* extracted fields and persists one
ValidationResult row per enabled rule, replacing any previous run so this is
safe to call again after a reviewer correction.

Rule shapes (pass/fail/warning + message wording) are matched 1:1 against
the frontend's former mock in src/data/mockDocuments.ts so Review.tsx and
the Dashboard render identically once wired to this API — same rule_name
strings, same message style, same "short-form survey number" /
"pre-1980" / duplicate-property-id cases.

`ValidationRuleConfig` rows (seeded in app/seed.py) gate whether a rule runs
at all via `.enabled` — a rule's own pass/fail/warning outcome is decided by
the specific check below, not by the config row's `.severity`, since a
single rule can land at different severities depending on the specific
failure (e.g. survey_number_format is a "warning" rule in general but a
completely empty field is still a hard "fail").
"""
from __future__ import annotations

import re
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.models import (
    MANDATORY_FIELDS,
    DocumentStatus,
    ExtractedField,
    FieldName,
    ValidationResult,
    ValidationRuleConfig,
    ValidationRuleResult,
    WaqfDocument,
)

FIELD_LABELS: dict[FieldName, str] = {
    FieldName.property_id: "Property ID",
    FieldName.mutawalli_name: "Mutawalli name",
    FieldName.survey_number: "Survey number",
    FieldName.registration_date: "Registration date",
    FieldName.extent: "Extent",
    FieldName.village: "Village",
}

# e.g. "412/2-A", "215/3", "301/1-C" — 3-4 digit survey block, 1-2 digit
# sub-division, optional hyphenated sub-plot letter.
SURVEY_NUMBER_FULL_RE = re.compile(r"^\d{3,4}/\d{1,2}(-[A-Za-z])?$")
# e.g. "88/1" — matches the general shape but the leading block is only
# 1-2 digits (shorter than the typical 3-4 digit block), so it's flagged
# for a human to verify rather than trusted outright.
SURVEY_NUMBER_SHORT_RE = re.compile(r"^\d{1,2}/\d{1,2}(-[A-Za-z])?$")

EARLIEST_PLAUSIBLE_DATE = date(1900, 1, 1)
DIGITISED_REGISTER_START = date(1980, 1, 1)

FieldMap = dict[FieldName, ExtractedField]


def _value(fields: FieldMap, name: FieldName) -> str | None:
    field = fields.get(name)
    return field.field_value if field is not None else None


def _rule_enabled(db: Session, key: str) -> bool:
    row = db.get(ValidationRuleConfig, key)
    return row.enabled if row is not None else True


# ---------------------------------------------------------------------------
# Individual rule checks — each returns (result, message)
# ---------------------------------------------------------------------------
def _check_mandatory_fields_present(
    db: Session, document: WaqfDocument, fields: FieldMap
) -> tuple[ValidationRuleResult, str]:
    missing = [name for name in MANDATORY_FIELDS if not _value(fields, name)]
    if not missing:
        return ValidationRuleResult.pass_, "All mandatory fields extracted."
    labels = [FIELD_LABELS[name] for name in missing]
    if len(labels) == 1:
        return ValidationRuleResult.fail, f"{labels[0]} could not be extracted."
    return (
        ValidationRuleResult.fail,
        f"{len(labels)} mandatory field(s) could not be extracted: {', '.join(labels)}.",
    )


def _check_survey_number_format(
    db: Session, document: WaqfDocument, fields: FieldMap
) -> tuple[ValidationRuleResult, str]:
    value = _value(fields, FieldName.survey_number)
    if not value:
        return ValidationRuleResult.fail, "Field is empty — manual entry required."
    value = value.strip()
    if SURVEY_NUMBER_FULL_RE.match(value):
        return ValidationRuleResult.pass_, "Matches expected survey number pattern."
    if SURVEY_NUMBER_SHORT_RE.match(value):
        return ValidationRuleResult.warning, "Short-form survey number — verify against register."
    return (
        ValidationRuleResult.fail,
        f"'{value}' does not match the expected survey number pattern (e.g. 412/2-A).",
    )


def _parse_date(raw: str) -> date | None:
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _check_date_plausibility(
    db: Session, document: WaqfDocument, fields: FieldMap
) -> tuple[ValidationRuleResult, str]:
    raw = _value(fields, FieldName.registration_date)
    if not raw:
        return ValidationRuleResult.fail, "Registration date is missing."
    parsed = _parse_date(raw)
    if parsed is None:
        return ValidationRuleResult.fail, f"'{raw}' is not a recognised date (expected YYYY-MM-DD)."
    today = date.today()
    if parsed > today:
        return ValidationRuleResult.fail, "Registration date is in the future."
    if parsed < EARLIEST_PLAUSIBLE_DATE:
        return ValidationRuleResult.fail, "Registration date predates any plausible Waqf record."
    if parsed < DIGITISED_REGISTER_START:
        return (
            ValidationRuleResult.warning,
            "Registration date predates digitised register (pre-1980); confirm manually.",
        )
    return ValidationRuleResult.pass_, "Registration date falls within valid range."


def _check_cross_document_consistency(
    db: Session, document: WaqfDocument, fields: FieldMap
) -> tuple[ValidationRuleResult, str]:
    property_id = _value(fields, FieldName.property_id)
    if not property_id:
        return (
            ValidationRuleResult.warning,
            "Property ID not extracted — cannot cross-check against other records.",
        )

    duplicates = (
        db.query(WaqfDocument)
        .join(ExtractedField, ExtractedField.document_id == WaqfDocument.id)
        .filter(
            ExtractedField.field_name == FieldName.property_id,
            ExtractedField.field_value == property_id,
            WaqfDocument.id != document.id,
        )
        .distinct()
        .all()
    )
    if duplicates:
        filenames = ", ".join(d.filename for d in duplicates)
        return (
            ValidationRuleResult.fail,
            f"Property ID {property_id} also appears in {filenames} — possible duplicate filing.",
        )
    return ValidationRuleResult.pass_, "No conflicting property ID found in other processed records."


# Order matches the project doc / mock: mandatory completeness, format,
# date sanity, then the cross-document check.
_RULES: list[tuple[str, "callable"]] = [
    ("mandatory_fields_present", _check_mandatory_fields_present),
    ("survey_number_format", _check_survey_number_format),
    ("date_plausibility", _check_date_plausibility),
    ("cross_document_consistency", _check_cross_document_consistency),
]


def run_validations(db: Session, document: WaqfDocument) -> list[ValidationResult]:
    """Runs every enabled rule against `document`'s current ExtractedField
    rows, replacing any ValidationResult rows already on record for it.

    Call this:
    - right after the OCR pipeline persists ExtractedField rows on upload
    - again after a reviewer submits corrections (values may have changed)

    Advances status extracted -> validated so a freshly-validated document
    leaves the "not yet looked at" bucket while still surfacing in the
    review queue (queue includes both extracted and validated). Left alone
    if the document is already past that point (e.g. flagged from an OCR
    failure, or already reviewed) — callers that need a specific status
    after this (e.g. submit_review) set it explicitly afterwards.
    """
    field_rows = db.query(ExtractedField).filter(ExtractedField.document_id == document.id).all()
    fields_by_name: FieldMap = {f.field_name: f for f in field_rows}

    db.query(ValidationResult).filter(ValidationResult.document_id == document.id).delete()

    results: list[ValidationResult] = []
    for rule_name, check in _RULES:
        if not _rule_enabled(db, rule_name):
            continue
        result, message = check(db, document, fields_by_name)
        row = ValidationResult(document_id=document.id, rule_name=rule_name, result=result, message=message)
        db.add(row)
        results.append(row)

    if document.status == DocumentStatus.extracted:
        document.status = DocumentStatus.validated

    db.flush()
    return results
