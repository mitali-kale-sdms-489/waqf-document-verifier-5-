# Waqf Document Verifier — Frontend

React 18 + TypeScript SPA for AI-assisted verification of Waqf-style records
(multi-script OCR, field extraction, cross-field validation, human-in-the-loop
review). Companion to the FastAPI backend described in
`Waqf_DocVerify_Architecture.md` / `Waqf_DocVerify_Implementation_Guide.md`.

## Stack

React 18 · TypeScript · Vite · Tailwind CSS · React Router v6 ·
React Hook Form + Zod · Axios · Recharts · shadcn/ui (Radix primitives) ·
react-hot-toast

## Getting started

```bash
npm install
cp .env.example .env      # optional — dev proxy covers localhost by default
npm run dev                # http://localhost:5173
```

The dev server proxies `/api/*` to `http://localhost:8000` (the FastAPI
backend). See `vite.config.ts`.

### Adding shadcn/ui components

```bash
npx shadcn@latest add button
npx shadcn@latest add "https://21st.dev/r/shadcn/table"
```

Components land in `src/components/ui/` per `components.json`.

## Project structure

```
src/
  api/            # axios client, request/response typing
  components/
    layout/       # app shell (sidebar nav, header)
    ui/            # shadcn/ui primitives (installed via CLI)
  hooks/
  lib/            # cn() and other utilities
  pages/          # one component per route
  routes/         # (reserved) route-level data loaders if needed
  types/          # domain types mirroring the backend schema
```

## Design system

Tokens live in `tailwind.config.js` (domain palette) and `src/index.css`
(shadcn CSS variables derived from that palette):

| Token | Hex | Use |
|---|---|---|
| `petrol-ink` | `#1B3A3A` | Primary — sidebar, headers |
| `registry-green` | `#2F5D50` | Verified / approved states |
| `brass` | `#B08D3E` | Accent — key actions, medium confidence |
| `stone` | `#EDEFEA` | App background |
| `rust` | `#A64B3C` | Flagged / low confidence / errors |

Fonts: **Inter** (UI/body), **Fraunces** (display headings, used sparingly),
**IBM Plex Mono** (record IDs, survey numbers, confidence %, dates).

Confidence bands (per architecture doc §8): green ≥0.9, amber 0.6–0.9,
red <0.6 — see `confidenceBand()` in `src/types/domain.ts`.

## Scripts

| Command | Purpose |
|---|---|
| `npm run dev` | Start Vite dev server |
| `npm run build` | Type-check + production build |
| `npm run preview` | Preview the production build locally |
| `npm run lint` | ESLint |
| `npm run typecheck` | `tsc --noEmit` |
