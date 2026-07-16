/**
 * Domain types mirroring the backend schema in Waqf_DocVerify_Architecture.md
 * (Section 5 — Database Schema) and the API spec (Section 6).
 */

export type ScriptType =
  | "urdu_nastaliq"
  | "marathi_devanagari"
  | "english_latin"
  | "hindi_devanagari"
  | "sanskrit_devanagari";

/** Single source of truth for script-type display labels — every place
 *  that used to do `scriptType === "urdu_nastaliq" ? "Urdu" : "Marathi"`
 *  should use this instead, since that ternary silently mislabels any third
 *  script type (e.g. English/Latin) as Marathi. Keep this in sync with the
 *  backend's ScriptType enum (app/models.py) — it currently has two more
 *  members (hindi_devanagari, sanskrit_devanagari) than this union did. */
export const SCRIPT_TYPE_LABELS: Record<ScriptType, string> = {
  urdu_nastaliq: "Urdu · Nastaliq",
  marathi_devanagari: "Marathi · Devanagari",
  english_latin: "English · Latin",
  hindi_devanagari: "Hindi · Devanagari",
  sanskrit_devanagari: "Sanskrit · Devanagari",
};

export const SCRIPT_TYPE_SHORT_LABELS: Record<ScriptType, string> = {
  urdu_nastaliq: "Urdu",
  marathi_devanagari: "Marathi",
  english_latin: "English",
  hindi_devanagari: "Hindi",
  sanskrit_devanagari: "Sanskrit",
};

export type DocumentStatus =
  | "uploaded"
  | "processing"
  | "extracted"
  | "validated"
  | "reviewed"
  | "approved"
  | "flagged";

/** Canonical field names extracted per document, per the extraction-assist response schema. */
export type FieldName =
  | "property_id"
  | "mutawalli_name"
  | "survey_number"
  | "registration_date"
  | "extent"
  | "village";

export const MANDATORY_FIELDS: FieldName[] = [
  "property_id",
  "mutawalli_name",
  "survey_number",
];

export function isMandatoryField(fieldName: FieldName): boolean {
  return MANDATORY_FIELDS.includes(fieldName);
}

export const FIELD_LABELS: Record<FieldName, string> = {
  property_id: "Property ID",
  mutawalli_name: "Mutawalli name",
  survey_number: "Survey number",
  registration_date: "Registration date",
  extent: "Extent",
  village: "Village",
};

/** Confidence bands per architecture doc Section 8: green ≥0.9, amber 0.6–0.9, red <0.6 */
export type ConfidenceBand = "high" | "medium" | "low";

export function confidenceBand(confidence: number): ConfidenceBand {
  if (confidence >= 0.9) return "high";
  if (confidence >= 0.6) return "medium";
  return "low";
}

/**
 * Result of the automated DPDP data-handling check run against a document
 * right after upload/extraction (per POC-C's blocking rule: no real Waqf
 * board record may proceed past review until DPDP terms exist — this is the
 * system-side check, replacing any user self-declaration at upload time).
 */
export type DpdpStatus = "checking" | "compliant" | "needs_review";

export interface WaqfDocument {
  id: string;
  filename: string;
  status: DocumentStatus;
  scriptType: ScriptType;
  isSynthetic: boolean;
  /** Outcome of the automated DPDP compliance check, run once extraction completes. */
  dpdpStatus: DpdpStatus;
  /** Human-readable reason for the dpdpStatus result, shown on hover/expand. */
  dpdpReason: string | null;
  uploadedAt: string;
  uploadedBy: string;
  overallConfidence: number | null;
  /**
   * Object URL for a file the user picked from their device. Seeded demo
   * records leave this null/undefined and Review.tsx falls back to the
   * stylised script facsimile instead.
   */
  previewUrl?: string | null;
  /** MIME type of the uploaded file, used to pick an image vs. PDF preview. */
  mimeType?: string | null;
  /** Original file size in bytes, shown in the upload list. */
  fileSizeBytes?: number | null;
  /**
   * Newline-separated OCR pipeline diagnostics: which engine won, any
   * script-hint corrections that were made (e.g. Sarvam re-run in the
   * corrected language), and why the translation pass did or didn't
   * populate fieldValueEn on each field. Null for records saved before
   * this was tracked. See Review.tsx's diagnostics panel.
   */
  extractionNotes?: string | null;
}

export interface ExtractedField {
  id: string;
  documentId: string;
  fieldName: FieldName;
  fieldValue: string | null;
  /** English transliteration/rendering of fieldValue, produced by a Gemini
   *  translation pass at extraction time (see backend
   *  gemini_engine.run_gemini_translation). Null for English/Latin-script
   *  documents, records extracted before this existed, or a failed/
   *  unconfigured translation call — always optional. */
  fieldValueEn: string | null;
  confidence: number;
  /** Which engine produced this read. sarvam_vision = Sarvam Vision 3B (primary,
   *  esp. Urdu Nastaliq), tesseract = Tesseract urd+mar / Surya fallback,
   *  shasan_slm = the old Shasan-SLM regex extraction-assist pass (Pod B; kept
   *  here only so older records still type-check, no longer produced),
   *  qwen_slm = Qwen2.5 running locally via Ollama, the current mapping-stage
   *  engine that replaced shasan_slm, gemini_vision = the vision-extraction
   *  fallback engine (replaced gpt4o_mini, which is kept here only so older
   *  records still type-check), reconciled = a human correction recorded
   *  during review. */
  source: "sarvam_vision" | "tesseract" | "shasan_slm" | "qwen_slm" | "gpt4o_mini" | "gemini_vision" | "reconciled";
}

export type ValidationRuleResult = "pass" | "fail" | "warning";

export interface ValidationResult {
  id: string;
  documentId: string;
  ruleName: string;
  result: ValidationRuleResult;
  message: string;
}

export type ReviewAction = "approve" | "correct" | "flag";

export interface Review {
  id: string;
  documentId: string;
  reviewerId: string;
  action: ReviewAction;
  notes: string | null;
  reviewedAt: string;
  durationSeconds: number | null;
}

export interface FieldCorrection {
  id: string;
  extractedFieldId: string;
  reviewId: string;
  previousValue: string | null;
  correctedValue: string;
  createdAt: string;
}

export interface AuditThroughputStats {
  documentsPerHour: number;
  manualBaselinePerHour: number;
  seededErrorCatchRate: number; // e.g. 18/20
  avgReviewSeconds: number;
}
