import { apiClient } from "@/api/client";
import type { Role } from "@/types/auth";

/**
 * Real backend calls for the Admin page (see app/routers/admin.py).
 * Replaces src/data/mockAdmin.ts's getOcrSettings/updateOcrSettings,
 * getUsers/createUser/updateUserRole/setUserActive,
 * getValidationRules/setValidationRuleEnabled, and getCerBenchmark —
 * response shapes were designed to match those mocks 1:1, so this is a
 * straight swap.
 */

export interface OcrSettings {
  /** Always "sarvam_vision" — read-only. Sarvam Vision 3B is always tried
   *  first by the pipeline now; engine choice beyond that is automatic
   *  (confidence-compared against Tesseract/Gemini Vision), not a setting. */
  primaryEngine: "sarvam_vision" | "tesseract" | "gemini_vision";
  useReconciliation: boolean;
  autoApproveHighConfidence: boolean;
  highConfidenceThreshold: number; // e.g. 0.9
  lowConfidenceThreshold: number; // e.g. 0.6
  /** Below this, Sarvam Vision's own confidence is treated as too low to
   *  trust alone, so Tesseract and Gemini Vision are also run and compared
   *  against it. */
  ocrFallbackThreshold: number; // e.g. 0.6
}

export type OcrSettingsUpdate = Partial<Omit<OcrSettings, "primaryEngine">>;

/** GET /admin/ocr-settings */
export async function getOcrSettings(): Promise<OcrSettings> {
  const { data } = await apiClient.get<OcrSettings>("/admin/ocr-settings");
  return data;
}

/** PATCH /admin/ocr-settings */
export async function updateOcrSettings(patch: OcrSettingsUpdate): Promise<OcrSettings> {
  const { data } = await apiClient.patch<OcrSettings>("/admin/ocr-settings", patch);
  return data;
}

// ---------------------------------------------------------------------------
// Users
// ---------------------------------------------------------------------------

export interface AdminUser {
  id: number;
  fullName: string;
  email: string;
  role: Role;
  active: boolean;
  lastLoginAt: string | null;
}

export interface CreateUserInput {
  fullName: string;
  email: string;
  role: Role;
}

/** POST /admin/users response — same shape as AdminUser plus a one-time
 *  temporary password (there's nowhere else for an admin-created account
 *  to get one from). Shown to the caller exactly once. */
export interface CreatedUser extends AdminUser {
  temporaryPassword: string;
}

/** GET /admin/users */
export async function getUsers(): Promise<AdminUser[]> {
  const { data } = await apiClient.get<AdminUser[]>("/admin/users");
  return data;
}

/** POST /admin/users */
export async function createUser(input: CreateUserInput): Promise<CreatedUser> {
  const { data } = await apiClient.post<CreatedUser>("/admin/users", input);
  return data;
}

/** PATCH /admin/users/{id}/role */
export async function updateUserRole(id: number, role: Role): Promise<AdminUser> {
  const { data } = await apiClient.patch<AdminUser>(`/admin/users/${id}/role`, { role });
  return data;
}

/** PATCH /admin/users/{id}/active */
export async function setUserActive(id: number, active: boolean): Promise<AdminUser> {
  const { data } = await apiClient.patch<AdminUser>(`/admin/users/${id}/active`, { active });
  return data;
}

// ---------------------------------------------------------------------------
// Validation rules
// ---------------------------------------------------------------------------

export interface ValidationRuleConfig {
  key: string;
  name: string;
  description: string;
  severity: "fail" | "warning";
  enabled: boolean;
}

/** GET /admin/validation-rules */
export async function getValidationRules(): Promise<ValidationRuleConfig[]> {
  const { data } = await apiClient.get<ValidationRuleConfig[]>("/admin/validation-rules");
  return data;
}

/** PATCH /admin/validation-rules/{key} */
export async function setValidationRuleEnabled(key: string, enabled: boolean): Promise<ValidationRuleConfig> {
  const { data } = await apiClient.patch<ValidationRuleConfig>(`/admin/validation-rules/${key}`, { enabled });
  return data;
}

// ---------------------------------------------------------------------------
// Multi-script OCR benchmark (POC-C Week 9 deliverable)
// ---------------------------------------------------------------------------

export interface CerBenchmarkEntry {
  scriptType: "urdu_nastaliq" | "marathi_devanagari";
  engine: "sarvam_vision" | "tesseract" | "surya" | "gemini_vision";
  /** Character Error Rate, as a fraction (0.048 = 4.8%). */
  cer: number;
  sampleSize: number;
}

const ENGINE_LABELS: Record<CerBenchmarkEntry["engine"], string> = {
  sarvam_vision: "Sarvam Vision 3B",
  tesseract: "Tesseract",
  surya: "Surya",
  gemini_vision: "Gemini Vision",
};

const SCRIPT_LABELS: Record<CerBenchmarkEntry["scriptType"], string> = {
  urdu_nastaliq: "Urdu · Nastaliq",
  marathi_devanagari: "Marathi · Devanagari",
};

export interface CerBenchmarkResult {
  entries: CerBenchmarkEntry[];
  /** Lowest-CER engine per script — the "engine selected per script" call. */
  selectedEngine: Record<CerBenchmarkEntry["scriptType"], CerBenchmarkEntry["engine"]>;
  engineLabels: typeof ENGINE_LABELS;
  scriptLabels: typeof SCRIPT_LABELS;
}

interface CerBenchmarkResponse {
  entries: CerBenchmarkEntry[];
  selectedEngine: Record<string, string>;
}

/** GET /admin/cer-benchmark. The backend only returns entries + the
 *  selected-engine map; the engine/script display labels are UI concerns
 *  the mock used to own, so they're attached here rather than on the API. */
export async function getCerBenchmark(): Promise<CerBenchmarkResult> {
  const { data } = await apiClient.get<CerBenchmarkResponse>("/admin/cer-benchmark");
  return {
    entries: data.entries,
    selectedEngine: data.selectedEngine as CerBenchmarkResult["selectedEngine"],
    engineLabels: ENGINE_LABELS,
    scriptLabels: SCRIPT_LABELS,
  };
}
