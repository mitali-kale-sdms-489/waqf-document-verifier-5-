import { apiClient } from "@/api/client";
import type {
  ExtractedField,
  FieldName,
  Review,
  ReviewAction,
  ValidationResult,
  WaqfDocument,
} from "@/types/domain";

/**
 * Real backend calls for the document pipeline. Route shapes and payloads
 * mirror what src/data/mockDocuments.ts used to simulate, so this is a
 * straight swap everywhere it's imported (see app/routers/documents.py).
 */

export interface DocumentDetail {
  document: WaqfDocument;
  fields: ExtractedField[];
  validations: ValidationResult[];
}

/** GET /documents — every document regardless of status, newest first. */
export async function getAllDocuments(): Promise<WaqfDocument[]> {
  const { data } = await apiClient.get<WaqfDocument[]>("/documents");
  return data;
}

/** GET /documents/queue — documents still awaiting review, oldest first. */
export async function getQueue(): Promise<WaqfDocument[]> {
  const { data } = await apiClient.get<WaqfDocument[]>("/documents/queue");
  return data;
}

/** GET /documents/{id} */
export async function getDocument(id: string): Promise<DocumentDetail | null> {
  try {
    const { data } = await apiClient.get<DocumentDetail>(`/documents/${id}`);
    return data;
  } catch (err) {
    const status = (err as { response?: { status?: number } }).response?.status;
    if (status === 404) return null;
    throw err;
  }
}

/** POST /documents/{id}/revalidate — force-reruns the validation-rule
 *  engine against the document's current fields, e.g. when a document has
 *  no validation results because it predates the rule engine being wired
 *  in (a reviewer editing a field would trigger this implicitly; this lets
 *  Review.tsx offer it as an explicit action instead). */
export async function revalidateDocument(documentId: string): Promise<ValidationResult[]> {
  const { data } = await apiClient.post<ValidationResult[]>(`/documents/${documentId}/revalidate`);
  return data;
}

export interface DashboardStats {
  pendingReview: number;
  approvedToday: number;
  flagged: number;
  avgConfidence: number | null;
}

/** GET /documents/stats/summary */
export async function getDashboardStats(): Promise<DashboardStats> {
  const { data } = await apiClient.get<DashboardStats>("/documents/stats/summary");
  return data;
}

export interface UploadResult {
  document: WaqfDocument;
  fields: ExtractedField[];
  diagnostics: { primaryEngine: string; notes: string[] };
}

/** POST /documents/upload — multipart file upload; runs OCR synchronously
 *  server-side and returns the extracted record. This can involve several
 *  sequential network calls server-side (Sarvam Vision job polling, and —
 *  when confidence is low — Tesseract/Gemini comparison plus a second
 *  Gemini call for field backfill), so it gets a much longer timeout than
 *  the rest of the API: the default 30s was routinely expiring client-side
 *  while the backend kept working and completed the upload anyway (visible
 *  only after a manual refresh, with the UI incorrectly reporting failure). */
export async function uploadDocument(file: File): Promise<UploadResult> {
  const formData = new FormData();
  formData.append("file", file);
  const { data } = await apiClient.post<UploadResult>("/documents/upload", formData, {
    headers: { "Content-Type": "multipart/form-data" },
    timeout: 120_000,
  });
  return data;
}

export interface SubmitReviewOptions {
  notes?: string | null;
  corrections?: Partial<Record<FieldName, string>>;
  durationSeconds?: number;
}

/** POST /documents/{id}/review */
export async function submitReview(
  documentId: string,
  action: ReviewAction,
  opts: SubmitReviewOptions = {}
): Promise<Review> {
  const { data } = await apiClient.post<Review>(`/documents/${documentId}/review`, {
    action,
    notes: opts.notes ?? null,
    corrections: opts.corrections ?? null,
    durationSeconds: opts.durationSeconds ?? null,
  });
  return data;
}

/** GET /documents/{id}/reviews — full review history, oldest first. */
export async function getDocumentReviews(documentId: string): Promise<Review[]> {
  const { data } = await apiClient.get<Review[]>(`/documents/${documentId}/reviews`);
  return data;
}

/** Latest "flag" review for a document, if any — lets the Dashboard show why
 *  a document was flagged without pulling in the whole Review workspace. */
export async function getFlagReason(
  documentId: string
): Promise<{ reason: string | null; reviewerId: string; reviewedAt: string } | null> {
  const reviews = await getDocumentReviews(documentId);
  const flagReviews = reviews.filter((r) => r.action === "flag");
  const latest = flagReviews[flagReviews.length - 1];
  if (!latest) return null;
  return { reason: latest.notes, reviewerId: latest.reviewerId, reviewedAt: latest.reviewedAt };
}
