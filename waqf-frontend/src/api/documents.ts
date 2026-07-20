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
  diagnostics: { primaryEngine: string; notes: string[] } | null;
}

/** POST /documents/upload — multipart file upload. The backend now only
 *  saves the file and creates the document row (status="processing")
 *  before responding; the actual OCR pipeline (Sarvam Vision job polling,
 *  Tesseract/Gemini comparison, Qwen-via-Ollama field mapping, Gemini
 *  backfill/translation) runs afterward as a background task, since that
 *  chain routinely took well over two minutes and no client-side timeout
 *  could reliably outlast it. This request should come back in well under
 *  a second; the 20s timeout here is just a safety margin, not a budget
 *  for OCR. Poll the returned document's id with pollDocumentUntilReady
 *  to find out when OCR actually finishes. */
export async function uploadDocument(file: File): Promise<UploadResult> {
  const formData = new FormData();
  formData.append("file", file);
  const { data } = await apiClient.post<UploadResult>("/documents/upload", formData, {
    headers: { "Content-Type": "multipart/form-data" },
    timeout: 20_000,
  });
  return data;
}

/** POST /documents/{id}/reupload — multipart file upload that replaces the
 *  file behind a flagged document and re-runs OCR against it, reusing the
 *  same document id (unlike uploadDocument, which always creates a new
 *  document). The backend caps this at MAX_REUPLOAD_ATTEMPTS and returns a
 *  409 once exhausted; the updated document's reuploadCount tells the
 *  Dashboard's flag dialog how many attempts remain. Same "processing"/poll
 *  shape as uploadDocument — the OCR pipeline runs as a background task. */
export async function reuploadDocument(documentId: string, file: File): Promise<UploadResult> {
  const formData = new FormData();
  formData.append("file", file);
  const { data } = await apiClient.post<UploadResult>(`/documents/${documentId}/reupload`, formData, {
    headers: { "Content-Type": "multipart/form-data" },
    timeout: 20_000,
  });
  return data;
}

export interface PollOptions {
  intervalMs?: number;
  /** Give up after this long and resolve with whatever state we last saw
   *  (still "processing" is possible — the document is safe either way,
   *  just still being worked on server-side; the caller can choose to poll
   *  again later rather than treat this as failure). */
  timeoutMs?: number;
}

/** Polls GET /documents/{id} until the background OCR task moves the
 *  document out of status="processing" (into extracted/validated/flagged),
 *  or until timeoutMs elapses. Replaces the old filename+uploader+recency
 *  matching hack — polling by id is exact, so there's no ambiguity and,
 *  since the document row already exists the moment upload() returns,
 *  there's nothing for the caller to "retry" and no way to create a
 *  duplicate by polling. */
export async function pollDocumentUntilReady(
  documentId: string,
  { intervalMs = 2000, timeoutMs = 5 * 60 * 1000 }: PollOptions = {}
): Promise<DocumentDetail | null> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const detail = await getDocument(documentId);
    if (detail && detail.document.status !== "processing") return detail;
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  return null;
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

export interface SupportedLanguage {
  code: string;
  label: string;
}

/** GET /documents/translate/languages — languages the flag-reason
 *  translator can translate into, for the Dashboard's language picker. */
export async function getTranslateLanguages(): Promise<SupportedLanguage[]> {
  const { data } = await apiClient.get<SupportedLanguage[]>("/documents/translate/languages");
  return data;
}

/** POST /documents/translate — translates free text (a supervisor's flag
 *  reason) into `targetLanguage` (e.g. "en-IN", "ur-IN"). Source language
 *  is auto-detected on the backend. */
export async function translateText(text: string, targetLanguage: string): Promise<string> {
  const { data } = await apiClient.post<{ translatedText: string; targetLanguage: string }>(
    "/documents/translate",
    { text, targetLanguage }
  );
  return data.translatedText;
}
