import type { Role } from "@/types/auth";

/**
 * In-memory mocks backing the Admin page. Mirrors what
 * GET/PATCH /api/admin/users, /api/admin/validation-rules, and
 * /api/admin/ocr-settings would return per the architecture doc — shaped so
 * Admin.tsx can be pointed at the real endpoints later without changing.
 */

export interface AdminUser {
  id: number;
  fullName: string;
  email: string;
  role: Role;
  active: boolean;
  lastLoginAt: string | null;
}

let userIdCounter = 100;
const users: AdminUser[] = [
  {
    id: 1,
    fullName: "System Administrator",
    email: "supervisor@waqf.gov.in",
    role: "SUPERVISOR",
    active: true,
    lastLoginAt: new Date(Date.now() - 20 * 60_000).toISOString(),
  },
  {
    id: 2,
    fullName: "Mohammed Ali",
    email: "user@waqf.gov.in",
    role: "USER",
    active: true,
    lastLoginAt: new Date(Date.now() - 3 * 3600_000).toISOString(),
  },
  {
    id: 3,
    fullName: "Fatima Sheikh",
    email: "fatima.sheikh@waqf.gov.in",
    role: "USER",
    active: true,
    lastLoginAt: new Date(Date.now() - 26 * 3600_000).toISOString(),
  },
  {
    id: 4,
    fullName: "Ravi Deshmukh",
    email: "ravi.deshmukh@waqf.gov.in",
    role: "SUPERVISOR",
    active: false,
    lastLoginAt: new Date(Date.now() - 21 * 24 * 3600_000).toISOString(),
  },
];

function delay<T>(value: T, ms = 300): Promise<T> {
  return new Promise((resolve) => setTimeout(() => resolve(value), ms));
}

export async function getUsers(): Promise<AdminUser[]> {
  return delay([...users].sort((a, b) => a.fullName.localeCompare(b.fullName)));
}

export interface CreateUserInput {
  fullName: string;
  email: string;
  role: Role;
}

export async function createUser(input: CreateUserInput): Promise<AdminUser> {
  userIdCounter += 1;
  const user: AdminUser = {
    id: userIdCounter,
    fullName: input.fullName,
    email: input.email,
    role: input.role,
    active: true,
    lastLoginAt: null,
  };
  users.push(user);
  return delay(user, 400);
}

export async function updateUserRole(id: number, role: Role): Promise<void> {
  const u = users.find((u) => u.id === id);
  if (u) u.role = role;
  return delay(undefined, 200);
}

export async function setUserActive(id: number, active: boolean): Promise<void> {
  const u = users.find((u) => u.id === id);
  if (u) u.active = active;
  return delay(undefined, 200);
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

const validationRules: ValidationRuleConfig[] = [
  {
    key: "mandatory_fields_present",
    name: "Mandatory fields present",
    description: "Property ID, mutawalli name, and survey number must all be extracted.",
    severity: "fail",
    enabled: true,
  },
  {
    key: "survey_number_format",
    name: "Survey number format",
    description: "Survey number must match the district's expected pattern (e.g. 412/2-A).",
    severity: "warning",
    enabled: true,
  },
  {
    key: "date_plausibility",
    name: "Registration date plausibility",
    description: "Flags registration dates outside the digitised register's valid range.",
    severity: "warning",
    enabled: true,
  },
  {
    key: "cross_document_consistency",
    name: "Cross-document consistency",
    description: "Cross-checks the extracted property ID against every other processed record and flags duplicates.",
    severity: "fail",
    enabled: true,
  },
];

export async function getValidationRules(): Promise<ValidationRuleConfig[]> {
  return delay([...validationRules]);
}

export async function setValidationRuleEnabled(key: string, enabled: boolean): Promise<void> {
  const r = validationRules.find((r) => r.key === key);
  if (r) r.enabled = enabled;
  return delay(undefined, 150);
}

// ---------------------------------------------------------------------------
// OCR / extraction settings — now backed by a real endpoint, see
// src/api/admin.ts (GET/PATCH /admin/ocr-settings). This used to be a purely
// local mock here that a supervisor could "edit" without it ever reaching
// the real OCR pipeline.
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Multi-script OCR benchmark (POC-C Week 9 deliverable: "CER reported per
// script per engine on the sample set; engine selected per script.")
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

// Nastaliq is materially harder than Devanagari per POC-C's named risk —
// every engine's CER is worse on the urdu_nastaliq rows below.
// NOTE: the gemini_vision rows below are the old GPT-4o mini numbers,
// relabeled — they are placeholders, not a real Gemini benchmark. Re-run
// the Week-9 CER benchmark against Gemini Vision and replace these.
const cerBenchmark: CerBenchmarkEntry[] = [
  { scriptType: "urdu_nastaliq", engine: "sarvam_vision", cer: 0.048, sampleSize: 100 },
  { scriptType: "urdu_nastaliq", engine: "gemini_vision", cer: 0.063, sampleSize: 100 },
  { scriptType: "urdu_nastaliq", engine: "surya", cer: 0.096, sampleSize: 100 },
  { scriptType: "urdu_nastaliq", engine: "tesseract", cer: 0.152, sampleSize: 100 },
  { scriptType: "marathi_devanagari", engine: "sarvam_vision", cer: 0.021, sampleSize: 100 },
  { scriptType: "marathi_devanagari", engine: "gemini_vision", cer: 0.028, sampleSize: 100 },
  { scriptType: "marathi_devanagari", engine: "surya", cer: 0.032, sampleSize: 100 },
  { scriptType: "marathi_devanagari", engine: "tesseract", cer: 0.039, sampleSize: 100 },
];

export interface CerBenchmarkResult {
  entries: CerBenchmarkEntry[];
  /** Lowest-CER engine per script — the "engine selected per script" call. */
  selectedEngine: Record<CerBenchmarkEntry["scriptType"], CerBenchmarkEntry["engine"]>;
  engineLabels: typeof ENGINE_LABELS;
  scriptLabels: typeof SCRIPT_LABELS;
}

export async function getCerBenchmark(): Promise<CerBenchmarkResult> {
  const bestByScript = (script: CerBenchmarkEntry["scriptType"]) =>
    cerBenchmark
      .filter((e) => e.scriptType === script)
      .reduce((best, e) => (e.cer < best.cer ? e : best)).engine;

  return delay(
    {
      entries: [...cerBenchmark],
      selectedEngine: {
        urdu_nastaliq: bestByScript("urdu_nastaliq"),
        marathi_devanagari: bestByScript("marathi_devanagari"),
      },
      engineLabels: ENGINE_LABELS,
      scriptLabels: SCRIPT_LABELS,
    },
    300
  );
}
