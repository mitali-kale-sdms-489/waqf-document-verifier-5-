# Waqf Document Verifier — Backend (POC-C)

FastAPI backend for the DocVerify Chain Extension, companion to the React
frontend in `waqf-document-verifierupdate14/`. Built in segments — this
delivery includes **Segments 1 and 2 of 4**.

## ⚠️ Security note (read this first)

Real API keys (Sarvam Vision, Gemini) were provided in chat and are sitting
in `.env`. That file is gitignored and **must never be committed, pasted
into chat, or forwarded** — if you hand this project to someone else, send
`.env.example` (placeholders only) and let them fill in their own `.env`.
Consider rotating the Sarvam/Gemini keys in their dashboards once this is
running, since they've already been exposed in a chat transcript.

## Segment roadmap

| Segment | Contents | Status |
|---|---|---|
| 1 | App scaffold, config, full DB schema, JWT auth (register/login/me) | ✅ delivered |
| 2 | Document upload, storage (local disk / S3), real OCR pipeline (Sarvam Vision, Gemini Vision fallback, Tesseract, stubbed Shasan-SLM), queue/get/list endpoints, file preview streaming | ✅ delivered |
| 3 | Validation rule engine (mandatory fields, survey number format, date plausibility, cross-document consistency), review + correction endpoints | ✅ delivered |
| 4 | Admin (users, validation-rule config, CER benchmark) + reports/dashboard throughput endpoints | ✅ this delivery |

All 4 segments are now delivered, and the frontend is fully wired to this
API (see "Notes on frontend wiring" below). What's left is data, not
code — see "What's still open after Segment 4".

The full DB schema (all tables) is already defined in `app/models.py` so
segments 2–4 don't need migrations for new tables — only new routers/services
on top of what's here.

## Synthetic sample set & CER benchmark (Weeks 1-8, 9, 10, 12)

```bash
# 1. Generate the 100-doc set (80 clean + 20 seeded-error) with ground truth
python -m scripts.generate_synthetic_samples

# 2. Run every configured OCR engine against it and write real CER numbers
#    (needs tesseract-ocr-urd/-mar + SARVAM_API_KEY/GEMINI_API_KEY for a
#    complete table; unconfigured engines are skipped, not fatal)
python -m scripts.run_cer_benchmark

# 3. Push the set through the real pipeline + validation engine + a
#    simulated review pass — prints Week-10 field accuracy and the
#    Week-12 seeded-error catch rate, and gives the Reports page real
#    throughput numbers instead of its cold-start fallback
python -m scripts.load_synthetic_samples
```

See each script's module docstring for details and flags.

## Setup

```bash
cd waqf-backend
python -m venv .venv && source .venv/bin/activate   # or your preferred env tool
pip install -r requirements.txt
cp .env.example .env   # then fill in real keys locally — the delivered .env already has them
uvicorn app.main:app --reload --port 8000
```

Also install Tesseract itself (the `pytesseract` package is just a wrapper)
with the Urdu + Marathi language packs, needed once Segment 2 lands:

```bash
# Debian/Ubuntu
sudo apt-get install tesseract-ocr tesseract-ocr-urd tesseract-ocr-mar
```

The frontend's Vite dev server proxies `/api/*` → `http://localhost:8000`
(see `vite.config.ts`), and the API client defaults to base URL `/api/v1`
(see `src/api/client.ts`) — so every route in this backend is mounted under
`/api/v1`.

## What's implemented in this segment

- `POST /api/v1/auth/register` — `{ fullName, email, password }` → new USER account (self-service always lands as USER, matching `registerUser()` in `mockAuth.ts`)
- `POST /api/v1/auth/login` — `{ email, password }` → `{ access_token, token_type, user }`
- `GET /api/v1/auth/me` — current user from Bearer token
- `POST /api/v1/auth/logout` — 204 (stateless JWT; client just drops the token)
- `GET /health` — reports which OCR/storage integrations have real credentials configured

Demo accounts seeded on first startup (same as `DEMO_CREDENTIALS` in `mockAuth.ts`):

| Role | Email | Password |
|---|---|---|
| Supervisor | supervisor@waqf.gov.in | Supervisor@Waqf2025 |
| User | user@waqf.gov.in | User@Waqf2025 |

Two extra seeded users (`fatima.sheikh@...`, `ravi.deshmukh@...`) match the
Admin page's mock user list in `mockAdmin.ts` for when Segment 4 wires up
`/api/v1/admin/users`.

## What's implemented in Segment 2

- `POST /api/v1/documents/upload` — multipart file upload (auth required). Runs the full OCR pipeline synchronously and returns `{ document, fields, diagnostics }`. `diagnostics` (primary engine used + notes) isn't part of the frontend's `WaqfDocument` type — it's extra, for debugging which engine actually ran.
- `GET /api/v1/documents/queue` — documents with status `extracted`/`validated`, oldest first.
- `GET /api/v1/documents` — every document, newest first (backs the Dashboard table).
- `GET /api/v1/documents/{id}` — `{ document, fields, validations: [] }`. `validations` is intentionally empty until Segment 3's rule engine lands.
- `GET /api/v1/documents/{id}/file` — streams the original uploaded scan (local disk or S3). Accepts the JWT via `Authorization: Bearer` **or** `?token=` query param, since `previewUrl` is consumed directly by `<img src>`/`<iframe src>` in `DocumentPreview.tsx`, which can't set headers. `previewUrl` in every document response already has a fresh token attached.

### OCR pipeline (`app/services/ocr/`)

1. **Quick script-detection pass** — Tesseract (`urd+mar`) runs first regardless of quality, purely to count Devanagari vs. Arabic Unicode code points and guess `scriptType`.
2. **Primary OCR** — Sarvam Vision 3B (via the `sarvamai` SDK's async Document Intelligence job) if `SARVAM_API_KEY` is set; falls back to the Tesseract pass above if Sarvam fails/isn't configured; falls back again to Gemini Vision transcription as a last resort (replaces the earlier GPT-4o mini fallback, which was unreliable in practice).
3. **Field extraction** — a local regex/heuristic parser (`shasan_stub.py`) standing in for Pod B's not-yet-live Shasan-SLM extraction-assist API, tagged `source="shasan_slm"` so the frontend's existing badge/label logic needs no changes when the real API arrives. Patterns are tuned to the property-ID/survey-number/extent shapes in the project's own synthetic sample set.
4. **Gap-filling** — any field the regex pass couldn't resolve with confidence ≥ 0.4 gets a second attempt from Gemini Vision's vision-based structured extraction (only if `GEMINI_API_KEY` is set), tagged `source="gemini_vision"`.
5. Every one of the six `FieldName`s is always persisted (value `null` if truly unresolved) so Review.tsx's per-field UI never has a missing row.

Every engine call is wrapped so a missing key, missing binary, or network failure degrades to the next engine rather than failing the upload — worst case, a document lands with `status="extracted"`, all fields `null`, and low confidence, ready for fully manual entry in Segment 3's review UI.

**Runtime dependency**: `pytesseract` is a wrapper — you still need the `tesseract` binary and language packs installed (see Setup below). Without it, Tesseract calls degrade cleanly to "unavailable," same as a missing API key.

## Notes on frontend wiring

`AuthContext.tsx`, `src/api/documents.ts`, `src/api/admin.ts`, and the new
`src/api/reports.ts` all call the real endpoints below now. The old mocks
in `src/data/mockAuth.ts`/`mockDocuments.ts`/`mockAdmin.ts` are unused —
left in place as a response-shape reference, not imported anywhere.

## What's implemented in Segment 3

`app/services/validation.py` — the validation-rule engine named in the
project doc, run automatically (no separate endpoint needed):

- **`mandatory_fields_present`** — fails if `property_id`, `mutawalli_name`,
  or `survey_number` is missing, naming exactly which field(s).
- **`survey_number_format`** — checks the extracted value against the
  survey-number shape seen in the synthetic set (e.g. `412/2-A`): full match
  → pass, a single-digit leading block (e.g. `8/1`) → warning ("short-form,
  verify against register"), empty → fail, anything else → fail.
- **`date_plausibility`** — fails on a missing or unparseable
  `registration_date` or a future date; warns on anything before 1980 (pre-
  digitised register); passes otherwise.
- **`cross_document_consistency`** — cross-checks the extracted
  `property_id` against every other document's extracted `property_id` in
  the DB and fails with the colliding filename(s) on a match; warns instead
  of failing if `property_id` itself couldn't be extracted (nothing to
  check yet); passes otherwise.

Each rule can be turned off via its `ValidationRuleConfig.enabled` flag
(seeded in `app/seed.py`; Segment 4 will add the admin endpoint to flip it —
until then it's DB-only). A rule's pass/fail/warning outcome is decided by
the specific check above, not by the config row's `severity` field, since
one rule can land at different severities depending on the specific failure
(e.g. `survey_number_format` is generally a "warning"-tier rule, but a
completely empty field is still a hard "fail").

**When it runs:**
1. Right after `POST /documents/upload`'s OCR pipeline persists
   `ExtractedField` rows — a document leaves upload as `status="validated"`
   (previously always `"extracted"`) with its `validations` list already
   populated, no separate call needed. Still runs (against zero fields, so
   everything fails) if the OCR pipeline itself blew up, so a fully-manual
   document still gets a useful "what's missing" signal.
2. Again inside `POST /documents/{id}/review` whenever the reviewer submits
   field corrections, since a correction can flip a previously-failing rule
   (a newly-typed-in survey number, a de-duplicated property ID after
   editing, etc.) — re-run before the review's own status transition
   (`reviewed`/`flagged`) is applied, so that transition always wins.

Each run **replaces** the document's previous `ValidationResult` rows
rather than appending, so `GET /documents/{id}` always reflects the current
field values, not a stale first pass. `GET /documents/{id}` also now sorts
`validations` into a fixed rule order (mandatory → format → date →
cross-document) for a stable UI instead of whatever order SQL happens to
return.

## What's implemented in Segment 4

All under `app/routers/admin.py` (users, validation-rule config, CER
benchmark — supervisor-only, `require_role(Role.SUPERVISOR)`) and the new
`app/routers/reports.py` (throughput/reports — also supervisor-only,
matching the `/reports` route's `allowedRoles` in `App.tsx`).

**Users** — replaces `mockAdmin.ts`'s `getUsers`/`createUser`/
`updateUserRole`/`setUserActive`:
- `GET /admin/users` — every user, alphabetical by name.
- `POST /admin/users` — `{ fullName, email, role }` → new account. The
  frontend's create-user form never collects a password (there's nowhere
  else for an admin-created account to get one), so the backend generates
  a random temporary one and returns it once as `temporaryPassword` on the
  response — an extra field beyond the frontend's `AdminUser` shape, same
  pattern as `diagnostics` on the upload response. Nothing but its bcrypt
  hash is ever persisted, so **hand it to the user out-of-band now** —
  there's no way to retrieve it again short of an admin password reset
  (not yet built).
- `PATCH /admin/users/{id}/role` — `{ role }`.
- `PATCH /admin/users/{id}/active` — `{ active }`. Refuses to let a
  supervisor deactivate their own account (`400`), since the mock never
  had to consider that this would actually lock account management going
  forward.

**Validation-rule config** — replaces `mockAdmin.ts`'s
`getValidationRules`/`setValidationRuleEnabled`, and is now the real
on/off switch for Segment 3's engine (`app/services/validation.py` checks
`ValidationRuleConfig.enabled` before running each rule):
- `GET /admin/validation-rules` — all four rules, alphabetical by key.
- `PATCH /admin/validation-rules/{key}` — `{ enabled }`. `severity` isn't
  editable here — it's descriptive metadata for the Admin UI, not what
  decides a rule's pass/fail/warning outcome (see `validation.py`'s
  module docstring for why).

**CER benchmark** (Week 9 deliverable) — replaces `mockAdmin.ts`'s
`getCerBenchmark`:
- `GET /admin/cer-benchmark` — every `CerBenchmarkEntry` row (seeded in
  `app/seed.py`), plus `selectedEngine`, the lowest-CER engine per script —
  the actual "engine selected per script" call the Week-9 demo-gate asks
  for. **The seeded numbers are placeholders** (carried over from the
  frontend mock, itself carrying over old GPT-4o-mini numbers relabeled as
  Gemini Vision) — nothing here runs OCR against the sample set and
  measures real CER yet. That's a data-generation task (run all
  configured engines over the 100-document synthetic set, diff against
  ground truth, insert real `CerBenchmarkEntry` rows), not just an
  endpoint, and is still open — see "What's still open" below.

**Reports/throughput** — replaces `mockDocuments.ts`'s
`getThroughputStats`/`getStatusBreakdown`/`getConfidenceDistribution`/
`getCorrectionsHistory`:
- `GET /reports/throughput` — the Wk-12 demo-gate headline number.
  `documentsPerHour` is derived from the actual average `durationSeconds`
  recorded on `approve`/`correct` reviews (`3600 / avg_seconds`);
  `seededErrorCatchRate` is the fraction of `isSynthetic` documents that
  ended up `flagged` or `reviewed` rather than sailing through untouched.
  `manualBaselinePerHour` is a fixed constant (6), same as the mock — there's
  no manual-baseline measurement to derive it from in this DB. Falls back
  to the same placeholder numbers the mock used (14/hr, 95s avg, 90% catch
  rate) before any real review activity exists, so the page never shows a
  blank/zero headline on a cold start.
- `GET /reports/status-breakdown` — document counts grouped by `status`.
- `GET /reports/confidence-distribution` — document counts bucketed into
  high/medium/low confidence bands (≥0.9 / ≥0.6 / below), matching
  `confidenceBand()` in `src/types/domain.ts`.
- `GET /reports/corrections` — every review, newest first, joined with its
  document's filename.

## What's still open after Segment 4

- **Frontend wiring** — ✅ done. Auth, Upload, Dashboard, Review, Reports,
  and all four Admin tabs (Users, Validation rules, OCR settings, CER
  benchmark) now call this API instead of the browser-local mocks in
  `src/data/`. Those mock files are unused dead code at this point (kept
  in place rather than deleted, in case they're still useful as a
  reference for response shapes).
- **Synthetic sample-set generation** — ✅ script added:
  `scripts/generate_synthetic_samples.py`. Generates template Waqf-style
  records (80 clean + 20 seeded-error by default) in Urdu/Nastaliq and
  Marathi/Devanagari, with a `ground_truth.json` manifest, under
  `storage/synthetic/`. **Read the script's docstring on fonts before
  trusting the rendered images**: without `Noto Nastaliq Urdu` /
  `Noto Sans Devanagari` (+ `arabic_reshaper`/`python-bidi` for proper
  Arabic shaping) installed, it falls back to a generic Unicode font and
  logs a loud warning — the ground-truth *text* is still exactly correct
  either way, only the rendered image's realism (and therefore Urdu CER)
  is affected.
- **Real CER benchmarking** — ✅ script added: `scripts/run_cer_benchmark.py`.
  Runs Tesseract/Sarvam Vision/Gemini Vision against every clean image in
  the synthetic set, computes CER via Levenshtein distance against the
  ground truth, and replaces the seeded placeholder `CerBenchmarkEntry`
  rows with measured ones. Needs `tesseract-ocr-urd`/`-mar` installed and
  `SARVAM_API_KEY`/`GEMINI_API_KEY` configured to produce a complete
  table — any engine that isn't usable in the current environment is
  skipped (reported as such) rather than failing the run.
- **Field-accuracy / seeded-error-catch scoring** — ✅ script added:
  `scripts/load_synthetic_samples.py`. Runs the full sample set through
  the real upload pipeline + validation engine (same code path as
  `POST /documents/upload`), simulates a reviewer's approve/flag decision
  on each result, and prints the Week-10 field-level extraction accuracy
  and the Week-12 seeded-error catch rate. This is also what gives the
  Reports page real throughput numbers instead of its cold-start
  fallbacks (14/hr, 95s avg, 90% catch rate).
- **None of the three scripts above have been run against real Sarvam/
  Gemini/Tesseract-with-language-packs output** — that requires network
  access and installed language packs/API keys this delivery environment
  doesn't have. Run them locally per each script's docstring; they're
  designed to degrade cleanly (skip, don't crash) around whichever
  engines aren't configured.
- **Password reset / admin-visible credentials** — a `POST /admin/users`
  temporary password is shown exactly once in the API response; there's no
  resend/reset flow yet if it's lost.

## Database

Defaults to local SQLite (`waqf_docverify.db`) for zero-setup dev. Set
`DATABASE_URL` in `.env` to a Postgres DSN for anything beyond local testing
— tables are created via `Base.metadata.create_all` on startup (no Alembic
migration yet; `alembic` is in requirements.txt for when the schema
stabilizes and you want real migrations instead).
