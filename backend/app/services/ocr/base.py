"""Shared types passed between OCR engine adapters and the pipeline."""
from __future__ import annotations

from dataclasses import dataclass

from app.models import ExtractionSource, FieldName, ScriptType


@dataclass
class RawTextResult:
    """Output of a full-page OCR pass, before field extraction."""

    text: str
    engine: ExtractionSource
    confidence: float  # 0..1, engine's own estimate of overall read quality
    error: str | None = None

    @property
    def ok(self) -> bool:
        return bool(self.text) and self.error is None


@dataclass
class FieldReading:
    value: str | None
    confidence: float
    source: ExtractionSource


FieldReadings = dict[FieldName, FieldReading]
