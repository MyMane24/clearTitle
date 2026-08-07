<div align="center">
  <img width="220" alt="clearTitle logo" src="src/assets/clearTitle.png" />
  <h1>clearTitle — AI Property Title Verification</h1>
  <p><em>Deeds, ECs, e-Khatas &amp; audits — one tamper-proof place.</em></p>
</div>

<p align="center">
  <strong>Run your property business without the chaos.</strong><br />
  AI + Blockchain property title verification platform built in Belagavi, Karnataka.
</p>

## What it does

clearTitle automates Indian property due diligence end-to-end — from raw Kannada/Hindi land deeds to a cryptographic proof of ownership on-chain.

- **Intake & OCR** — Digital processing of Sale Deeds, Encumbrance Certificates (EC), e-Khata, and sanctioned layout plans.
- **VLM Analysis** — Vision-Language Models parse complex Indian-language & regional land terminology.
- **Trust Score & Red Flags** — Unified verification status highlighting Chain of Title, area discrepancies, and potential fraud risks.
- **Blockchain Layer** — Future-ready property tokenization with tamper-evident ownership & immutable transaction history on Polygon.

## Pages

| Route | What it is |
| ----- | ---------- |
| `/` | Landing page — hero, four-step pipeline, live audit demo, market & revenue, FAQ |
| `/#/app` | Verification Dashboard — upload PDFs, run the OCR pipeline, view results, run agentic verification, browse case history |

## Tech Stack

| Layer   | Technology |
| ------- | ---------- |
| Frontend| React 19, Vite 6, TypeScript, Tailwind CSS 4, lucide-react, motion |
| Backend | Express (dev server), tsx |
| AI      | `@google/genai` (Vision-Language API) |
| 3D/UI   | three.js (interactive hero background) |

## Getting Started

**Prerequisites:** Node.js 18+

1. Install dependencies:

   ```bash
   npm install
   ```

2. Configure environment variables:

   ```bash
   cp .env.example .env
   ```

   - `AI_API_KEY` — your VLM AI API key. Without it the audit endpoint returns an intelligent mock report so you can still explore the UI.

3. Run the app (dev server with API + Vite HMR on port 3000):

   ```bash
   npm run dev
   ```

## Scripts

| Command        | Description                                        |
| -------------- | -------------------------------------------------- |
| `npm run dev`  | Start dev server (Express + Vite middleware) on :3000 |
| `npm run build`| Build the Vite frontend and bundle the Express server to `dist/` |
| `npm start`    | Run the production server from `dist/`             |
| `npm run lint` | Type-check the project with `tsc --noEmit`         |

> In the Docker deployment the built SPA is served by the FastAPI backend instead of this Express server.

## API

- `GET /api/health` — service health check
- `POST /api/verify-property` — runs an AI title audit on provided document text and returns a structured report (trust score, red flags, chain of title, blockchain certificate hash). Falls back to a mock report when `AI_API_KEY` is unset.
- `GET /api/cases`, `POST /api/upload`, `GET /api/status/{case_id}`, … — dashboard endpoints (see the root `README.md`)

## Project Structure

```
├── src/
│   ├── components/      # Landing-page sections (Navbar, Hero, FAQ, ...)
│   ├── dashboard/       # Verification Dashboard — upload, results, report, history
│   ├── api/backend.ts   # API client used by the dashboard
│   ├── data/            # Static landing-page content
│   ├── types.ts         # Shared TypeScript types
│   ├── App.tsx          # Routes: homepage + /#/app dashboard
│   └── index.css        # Tailwind + brand fonts/gradients
├── public/              # Favicon & static assets
├── src/assets/          # Brand assets (logo PNG)
├── server.ts            # Express + AI audit API + Vite/static serving
├── index.html
└── vite.config.ts
```

## UI Design System

- **Palette** — Cream `#FFF8F2`, stone neutrals, orange brand (`#ea580c`, `#f97316`, amber `#fbbf24`)
- **Fonts** — Inter (body), Plus Jakarta Sans (display), Instrument Serif (accent italics)
- **Icons** — lucide-react

## Deployment

```bash
npm run build
npm start
```
