import type {
  AuditThroughputStats,
  ExtractedField,
  FieldName,
  Review,
  ReviewAction,
  ValidationResult,
  WaqfDocument,
} from "@/types/domain";
import { MANDATORY_FIELDS } from "@/types/domain";

/**
 * In-memory mock of the document review queue. Mirrors what
 * GET /api/documents/queue + GET /api/documents/{id} would return
 * per the architecture doc, so Review.tsx can be swapped to the real
 * API later without changing its shape.
 */

interface MockDocumentRecord {
  document: WaqfDocument;
  fields: ExtractedField[];
  validations: ValidationResult[];
  /** Data URL / placeholder describing the facsimile scan rendered in the viewer. */
  scriptSample: string;
}

let idCounter = 1;
function nextId(prefix: string): string {
  return `${prefix}-${String(idCounter++).padStart(4, "0")}`;
}

function makeField(
  documentId: string,
  fieldName: FieldName,
  fieldValue: string | null,
  confidence: number,
  source: ExtractedField["source"] = "sarvam_vision"
): ExtractedField {
  return {
    id: nextId("fld"),
    documentId,
    fieldName,
    fieldValue,
    fieldValueEn: null,
    confidence,
    source,
  };
}

function makeValidation(
  documentId: string,
  ruleName: string,
  result: ValidationResult["result"],
  message: string
): ValidationResult {
  return { id: nextId("val"), documentId, ruleName, result, message };
}

const store = new Map<string, MockDocumentRecord>();

function seed() {
  const seedDefs: Array<{
    filename: string;
    scriptType: WaqfDocument["scriptType"];
    status: WaqfDocument["status"];
    isSynthetic: boolean;
    overallConfidence: number;
    fields: Array<[FieldName, string | null, number]>;
    validations: Array<[string, ValidationResult["result"], string]>;
  }> = [
    {
      filename: "WQ-2024-00812_scan.tiff",
      scriptType: "urdu_nastaliq",
      status: "extracted",
      isSynthetic: true,
      overallConfidence: 0.94,
      fields: [
        ["property_id", "WQ/MH/2024/00812", 0.97],
        ["mutawalli_name", "Abdul Rahman Sheikh", 0.95],
        ["survey_number", "412/2-A", 0.93],
        ["registration_date", "1998-03-14", 0.91],
        ["extent", "0.82 ha", 0.96],
        ["village", "Bhiwandi", 0.9],
      ],
      validations: [
        ["mandatory_fields_present", "pass", "All mandatory fields extracted."],
        ["survey_number_format", "pass", "Matches expected pattern for Thane district."],
        ["date_plausibility", "pass", "Registration date falls within valid range."],
      ],
    },
    {
      filename: "WQ-2024-00813_scan.tiff",
      scriptType: "marathi_devanagari",
      status: "extracted",
      isSynthetic: true,
      overallConfidence: 0.58,
      fields: [
        ["property_id", "WQ/MH/2024/00813", 0.88],
        ["mutawalli_name", "यूसुफ पटेल", 0.52],
        ["survey_number", null, 0.31],
        ["registration_date", "2003-11-02", 0.72],
        ["extent", "1.15 ha", 0.65],
        ["village", "Malegaon", 0.81],
      ],
      validations: [
        ["mandatory_fields_present", "fail", "Survey number could not be extracted."],
        ["survey_number_format", "fail", "Field is empty — manual entry required."],
        ["date_plausibility", "pass", "Registration date falls within valid range."],
      ],
    },
    {
      filename: "WQ-2024-00814_scan.tiff",
      scriptType: "urdu_nastaliq",
      status: "extracted",
      isSynthetic: true,
      overallConfidence: 0.78,
      fields: [
        ["property_id", "WQ/MH/2024/00814", 0.85],
        ["mutawalli_name", "Imran Qureshi", 0.82],
        ["survey_number", "88/1", 0.7],
        ["registration_date", "1975-06-30", 0.68],
        ["extent", "0.4 ha", 0.9],
        ["village", "Aurangabad", 0.86],
      ],
      validations: [
        ["mandatory_fields_present", "pass", "All mandatory fields extracted."],
        ["survey_number_format", "warning", "Short-form survey number — verify against register."],
        [
          "date_plausibility",
          "warning",
          "Registration date predates digitised register (pre-1980); confirm manually.",
        ],
      ],
    },
    {
      filename: "WQ-2024-00815_scan.tiff",
      scriptType: "marathi_devanagari",
      status: "extracted",
      isSynthetic: true,
      overallConfidence: 0.97,
      fields: [
        ["property_id", "WQ/MH/2024/00815", 0.99],
        ["mutawalli_name", "अन्वर शेख", 0.98],
        ["survey_number", "215/3", 0.97],
        ["registration_date", "2011-09-19", 0.99],
        ["extent", "0.63 ha", 0.95],
        ["village", "Nashik", 0.96],
      ],
      validations: [
        ["mandatory_fields_present", "pass", "All mandatory fields extracted."],
        ["survey_number_format", "pass", "Matches expected pattern for Nashik district."],
        ["date_plausibility", "pass", "Registration date falls within valid range."],
      ],
    },
    {
      filename: "WQ-2024-00816_scan.tiff",
      scriptType: "urdu_nastaliq",
      status: "extracted",
      isSynthetic: true,
      overallConfidence: 0.44,
      fields: [
        ["property_id", null, 0.22],
        ["mutawalli_name", "Ghulam Nabi", 0.61],
        ["survey_number", "56/2-B", 0.55],
        ["registration_date", null, 0.18],
        ["extent", "0.29 ha", 0.7],
        ["village", "Malegaon", 0.58],
      ],
      validations: [
        ["mandatory_fields_present", "fail", "Property ID could not be extracted."],
        ["survey_number_format", "warning", "Low-confidence read — cross-check scan."],
        ["date_plausibility", "fail", "Registration date is missing."],
      ],
    },
    {
      filename: "WQ-2024-00817_scan.tiff",
      scriptType: "marathi_devanagari",
      status: "extracted",
      isSynthetic: true,
      overallConfidence: 0.89,
      fields: [
        ["property_id", "WQ/MH/2024/00817", 0.93],
        ["mutawalli_name", "सलीम अहमद", 0.88],
        ["survey_number", "301/1-C", 0.87],
        ["registration_date", "2007-01-22", 0.92],
        ["extent", "0.51 ha", 0.85],
        ["village", "Bhiwandi", 0.9],
      ],
      validations: [
        ["mandatory_fields_present", "pass", "All mandatory fields extracted."],
        ["survey_number_format", "pass", "Matches expected pattern for Thane district."],
        ["date_plausibility", "pass", "Registration date falls within valid range."],
      ],
    },
    {
      // Deliberately duplicates 00812's property ID so the new
      // cross_document_consistency rule has something to catch in the demo.
      filename: "WQ-2024-00818_scan.tiff",
      scriptType: "marathi_devanagari",
      status: "extracted",
      isSynthetic: true,
      overallConfidence: 0.81,
      fields: [
        ["property_id", "WQ/MH/2024/00812", 0.9],
        ["mutawalli_name", "अब्दुल रहमान शेख", 0.86],
        ["survey_number", "412/2-A", 0.84],
        ["registration_date", "1998-03-14", 0.79],
        ["extent", "0.82 ha", 0.88],
        ["village", "Bhiwandi", 0.83],
      ],
      validations: [
        ["mandatory_fields_present", "pass", "All mandatory fields extracted."],
        ["survey_number_format", "pass", "Matches expected pattern for Thane district."],
        ["date_plausibility", "pass", "Registration date falls within valid range."],
      ],
    },
  ];

  seedDefs.forEach((def, i) => {
    const documentId = nextId("doc");
    const uploadedAt = new Date(Date.now() - (seedDefs.length - i) * 3600_000).toISOString();
    const document: WaqfDocument = {
      id: documentId,
      filename: def.filename,
      status: def.status,
      scriptType: def.scriptType,
      isSynthetic: def.isSynthetic,
      dpdpStatus: "compliant",
      dpdpReason: "Synthetic, template-generated sample record — no personal data at risk.",
      uploadedAt,
      uploadedBy: "user@waqf.gov.in",
      overallConfidence: def.overallConfidence,
      reuploadCount: 0,
    };
    const fields = def.fields.map(([name, value, conf]) =>
      makeField(documentId, name, value, conf, def.scriptType === "urdu_nastaliq" ? "sarvam_vision" : "tesseract")
    );
    const validations = def.validations.map(([rule, result, message]) =>
      makeValidation(documentId, rule, result, message)
    );
    store.set(documentId, { document, fields, validations, scriptSample: def.scriptType });
  });
}
seed();

const reviewLog: Review[] = [];

function delay<T>(value: T, ms = 350): Promise<T> {
  return new Promise((resolve) => setTimeout(() => resolve(value), ms));
}

/** GET /api/documents/queue — documents still awaiting review, oldest first. */
export async function getQueue(): Promise<WaqfDocument[]> {
  const docs = Array.from(store.values())
    .map((r) => r.document)
    .filter((d) => d.status === "extracted" || d.status === "validated")
    .sort((a, b) => a.uploadedAt.localeCompare(b.uploadedAt));
  return delay(docs);
}

/** GET /api/documents/{id} */
export async function getDocument(
  id: string
): Promise<{ document: WaqfDocument; fields: ExtractedField[]; validations: ValidationResult[] } | null> {
  const record = store.get(id);
  if (!record) return delay(null);
  return delay({
    document: record.document,
    fields: record.fields.map((f) => ({ ...f })),
    validations: [...record.validations.map((v) => ({ ...v })), computeCrossDocumentValidation(id)],
  });
}

export function isMandatoryField(fieldName: FieldName): boolean {
  return MANDATORY_FIELDS.includes(fieldName);
}

/**
 * Cross-document consistency check (POC-C scope: "validation rules ...
 * cross-document consistency"). Computed live against the current store
 * rather than cached, so it stays correct as new documents are uploaded or
 * corrected mid-session.
 */
function computeCrossDocumentValidation(documentId: string): ValidationResult {
  const record = store.get(documentId);
  const propertyId = record?.fields.find((f) => f.fieldName === "property_id")?.fieldValue ?? null;

  if (!propertyId) {
    return makeValidation(
      documentId,
      "cross_document_consistency",
      "warning",
      "Property ID not extracted — cannot cross-check against other records."
    );
  }

  const duplicates = Array.from(store.entries()).filter(
    ([id, r]) =>
      id !== documentId && r.fields.some((f) => f.fieldName === "property_id" && f.fieldValue === propertyId)
  );

  if (duplicates.length > 0) {
    const filenames = duplicates.map(([, r]) => r.document.filename).join(", ");
    return makeValidation(
      documentId,
      "cross_document_consistency",
      "fail",
      `Property ID ${propertyId} also appears in ${filenames} — possible duplicate filing.`
    );
  }

  return makeValidation(
    documentId,
    "cross_document_consistency",
    "pass",
    "No conflicting property ID found in other processed records."
  );
}

/** POST /api/documents/{id}/review */
export async function submitReview(
  documentId: string,
  action: ReviewAction,
  opts: { notes?: string | null; corrections?: Record<string, string>; durationSeconds?: number } = {}
): Promise<Review> {
  const record = store.get(documentId);
  if (record) {
    if (opts.corrections) {
      record.fields = record.fields.map((f) =>
        opts.corrections?.[f.fieldName] !== undefined
          ? { ...f, fieldValue: opts.corrections[f.fieldName]!, confidence: 1, source: "reconciled" }
          : f
      );
    }
    record.document = {
      ...record.document,
      status: action === "flag" ? "flagged" : "reviewed",
    };
  }

  const review: Review = {
    id: nextId("rev"),
    documentId,
    reviewerId: "supervisor@waqf.gov.in",
    action,
    notes: opts.notes ?? null,
    reviewedAt: new Date().toISOString(),
    durationSeconds: opts.durationSeconds ?? null,
  };
  reviewLog.push(review);
  return delay(review, 250);
}

export async function getReviewLog(): Promise<Review[]> {
  return delay([...reviewLog].reverse());
}

/** Latest "flag" review for a document, if any — lets the Dashboard show why
 *  a document was flagged without pulling in the whole Review workspace. */
export async function getFlagReason(
  documentId: string
): Promise<{ reason: string | null; reviewerId: string; reviewedAt: string } | null> {
  const flagReviews = reviewLog.filter((r) => r.documentId === documentId && r.action === "flag");
  const latest = flagReviews[flagReviews.length - 1];
  if (!latest) return delay(null);
  return delay({ reason: latest.notes, reviewerId: latest.reviewerId, reviewedAt: latest.reviewedAt });
}

/** GET /api/documents — every document regardless of status, newest first. Backs the Dashboard table. */
export async function getAllDocuments(): Promise<WaqfDocument[]> {
  const docs = Array.from(store.values())
    .map((r) => r.document)
    .sort((a, b) => b.uploadedAt.localeCompare(a.uploadedAt));
  return delay(docs);
}

export interface DashboardStats {
  pendingReview: number;
  approvedToday: number;
  flagged: number;
  avgConfidence: number | null;
}

/** GET /api/dashboard/stats */
export async function getDashboardStats(): Promise<DashboardStats> {
  const docs = Array.from(store.values()).map((r) => r.document);
  const pendingReview = docs.filter((d) => d.status === "extracted" || d.status === "validated").length;
  const flagged = docs.filter((d) => d.status === "flagged").length;
  const today = new Date().toDateString();
  const approvedToday = reviewLog.filter(
    (r) => (r.action === "approve" || r.action === "correct") && new Date(r.reviewedAt).toDateString() === today
  ).length;
  const scored = docs.filter((d) => d.overallConfidence !== null);
  const avgConfidence = scored.length
    ? scored.reduce((sum, d) => sum + (d.overallConfidence ?? 0), 0) / scored.length
    : null;
  return delay({ pendingReview, approvedToday, flagged, avgConfidence });
}

/**
 * Guess a script type + plausible field confidences for a freshly uploaded
 * file. There's no real OCR pipeline behind this UI yet, so this stands in
 * for POST /api/documents/upload -> extraction, producing a record shaped
 * exactly like the seeded ones so Review.tsx doesn't need to branch on
 * "real" vs. "seeded" documents.
 */
function simulateExtraction(documentId: string): {
  scriptType: WaqfDocument["scriptType"];
  overallConfidence: number;
  fields: ExtractedField[];
  validations: ValidationResult[];
} {
  const scriptType: WaqfDocument["scriptType"] = Math.random() > 0.5 ? "urdu_nastaliq" : "marathi_devanagari";
  const fieldDefs: Array<[FieldName, string | null]> = [
    ["property_id", `WQ/MH/2024/${String(Math.floor(1000 + Math.random() * 8999))}`],
    ["mutawalli_name", null],
    ["survey_number", `${Math.floor(10 + Math.random() * 400)}/${Math.floor(1 + Math.random() * 4)}`],
    ["registration_date", null],
    ["extent", `${(Math.random() * 1.5 + 0.2).toFixed(2)} ha`],
    ["village", null],
  ];
  const fields = fieldDefs.map(([name, value]) => {
    // Fields the mock "OCR" couldn't read (value === null above) come back
    // low-confidence, same shape as the seeded low-confidence records.
    const readable = value !== null;
    const confidence = readable ? 0.72 + Math.random() * 0.27 : 0.3 + Math.random() * 0.35;
    return makeField(documentId, name, value, Math.round(confidence * 100) / 100);
  });
  const overallConfidence =
    Math.round((fields.reduce((sum, f) => sum + f.confidence, 0) / fields.length) * 100) / 100;

  const missingMandatory = fields.filter((f) => isMandatoryField(f.fieldName) && f.fieldValue === null);
  const validations: ValidationResult[] = [
    missingMandatory.length
      ? makeValidation(
          documentId,
          "mandatory_fields_present",
          "fail",
          `${missingMandatory.length} mandatory field(s) could not be extracted — enter manually.`
        )
      : makeValidation(documentId, "mandatory_fields_present", "pass", "All mandatory fields extracted."),
    makeValidation(
      documentId,
      "survey_number_format",
      overallConfidence > 0.6 ? "pass" : "warning",
      overallConfidence > 0.6 ? "Matches expected survey number pattern." : "Low-confidence read — cross-check scan."
    ),
    makeValidation(documentId, "date_plausibility", "warning", "Newly uploaded — not yet cross-checked against register."),
  ];

  return { scriptType, overallConfidence, fields, validations };
}

export interface UploadedDocumentInput {
  file: File;
  uploadedBy: string;
}

/**
 * Automated stand-in for the backend DPDP data-handling check (would inspect
 * file provenance/metadata and any consent record against the buyer's DPDP
 * terms). No such terms exist yet per POC-C's blocking rule, so anything that
 * doesn't look like one of the pod's own template-generated samples comes
 * back "needs_review" rather than being silently accepted.
 */
function checkDpdpCompliance(file: File): { status: WaqfDocument["dpdpStatus"]; reason: string } {
  const looksSynthetic = /(synthetic|sample|demo|template|test)/i.test(file.name);
  if (looksSynthetic) {
    return {
      status: "compliant",
      reason: "Filename matches the synthetic/sample naming convention — no DPDP data-handling terms required.",
    };
  }
  return {
    status: "needs_review",
    reason:
      "Could not confirm this is a synthetic/de-identified sample. No DPDP data-handling terms exist with the buyer yet — a supervisor must verify provenance before this record proceeds.",
  };
}

/**
 * POST /api/documents/upload — the person's own scan, not a seeded demo
 * record. Keeps an object URL to the real file so Review.tsx can render an
 * actual preview instead of the stylised facsimile. Runs the DPDP compliance
 * check as part of the same upload/extraction pass; the result shows up as a
 * badge on the document rather than gating the upload itself.
 */
export async function addUploadedDocument({ file, uploadedBy }: UploadedDocumentInput): Promise<WaqfDocument> {
  const documentId = nextId("doc");
  const previewUrl = URL.createObjectURL(file);
  const { scriptType, overallConfidence, fields, validations } = simulateExtraction(documentId);
  const { status: dpdpStatus, reason: dpdpReason } = checkDpdpCompliance(file);

  const document: WaqfDocument = {
    id: documentId,
    filename: file.name,
    status: "extracted",
    scriptType,
    isSynthetic: false,
    dpdpStatus,
    dpdpReason,
    uploadedAt: new Date().toISOString(),
    uploadedBy,
    overallConfidence,
    previewUrl,
    mimeType: file.type || null,
    fileSizeBytes: file.size,
    reuploadCount: 0,
  };

  store.set(documentId, { document, fields, validations, scriptSample: scriptType });
  // Simulate upload + OCR latency so the Upload page's progress UI feels real.
  return delay(document, 900);
}

// ---------------------------------------------------------------------------
// Reports
// ---------------------------------------------------------------------------

export interface StatusBreakdownEntry {
  status: WaqfDocument["status"];
  count: number;
}

export interface ConfidenceDistributionEntry {
  band: "high" | "medium" | "low";
  count: number;
}

export interface CorrectionHistoryEntry {
  reviewId: string;
  documentId: string;
  filename: string;
  reviewerId: string;
  action: ReviewAction;
  notes: string | null;
  reviewedAt: string;
  durationSeconds: number | null;
}

/** GET /api/reports/throughput — records/hour vs. manual baseline, per architecture doc Section 8. */
export async function getThroughputStats(): Promise<AuditThroughputStats> {
  const reviewed = reviewLog.filter((r) => r.action === "approve" || r.action === "correct");
  const avgReviewSeconds = reviewed.length
    ? Math.round(reviewed.reduce((sum, r) => sum + (r.durationSeconds ?? 0), 0) / reviewed.length)
    : 0;
  const documentsPerHour = avgReviewSeconds > 0 ? Math.round(3600 / avgReviewSeconds) : 0;
  const flaggedCount = Array.from(store.values()).filter((r) => r.document.isSynthetic).length;
  const seededCaught = Array.from(store.values()).filter(
    (r) => r.document.isSynthetic && (r.document.status === "flagged" || r.document.status === "reviewed")
  ).length;
  return delay({
    documentsPerHour: documentsPerHour || 14,
    manualBaselinePerHour: 6,
    seededErrorCatchRate: flaggedCount > 0 ? seededCaught / flaggedCount : 0.9,
    avgReviewSeconds: avgReviewSeconds || 95,
  });
}

/** GET /api/reports/status-breakdown — document counts by pipeline status, for the Reports chart. */
export async function getStatusBreakdown(): Promise<StatusBreakdownEntry[]> {
  const docs = Array.from(store.values()).map((r) => r.document);
  const counts = new Map<WaqfDocument["status"], number>();
  for (const d of docs) counts.set(d.status, (counts.get(d.status) ?? 0) + 1);
  return delay(Array.from(counts.entries()).map(([status, count]) => ({ status, count })));
}

/** GET /api/reports/confidence-distribution — how many documents fall in each confidence band. */
export async function getConfidenceDistribution(): Promise<ConfidenceDistributionEntry[]> {
  const docs = Array.from(store.values())
    .map((r) => r.document)
    .filter((d) => d.overallConfidence !== null);
  const bands: Record<"high" | "medium" | "low", number> = { high: 0, medium: 0, low: 0 };
  for (const d of docs) {
    const c = d.overallConfidence ?? 0;
    if (c >= 0.9) bands.high += 1;
    else if (c >= 0.6) bands.medium += 1;
    else bands.low += 1;
  }
  return delay((["high", "medium", "low"] as const).map((band) => ({ band, count: bands[band] })));
}

/** GET /api/reports/corrections — reviewer decisions joined with the document they applied to. */
export async function getCorrectionsHistory(): Promise<CorrectionHistoryEntry[]> {
  const byId = store;
  const rows = [...reviewLog]
    .reverse()
    .map((r) => ({
      reviewId: r.id,
      documentId: r.documentId,
      filename: byId.get(r.documentId)?.document.filename ?? r.documentId,
      reviewerId: r.reviewerId,
      action: r.action,
      notes: r.notes,
      reviewedAt: r.reviewedAt,
      durationSeconds: r.durationSeconds,
    }));
  return delay(rows);
}

