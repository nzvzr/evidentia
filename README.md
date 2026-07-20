<p align="center">
  <img src="./public/evidentia-logo.png" alt="Evidentia logo" width="420" />
</p>

<h1 align="center">Evidentia</h1>

<p align="center">
  Persona-aware documentation agent for role-specific workflows, cited recommendations, risks, dashboards, and exportable playbooks.
</p>

---

**Evidentia** transforms static enterprise documentation into role-specific workflows, risk insights, traceable citations, dashboard metrics, and exportable playbooks.

Built for the **RAISE Summit Hackathon**.

> Static documentation is written once, but every team uses it differently. Evidentia turns scattered company docs into actionable playbooks adapted to each role, market, and business context.

Evidentia now includes:

- a **Next.js** frontend (App Router, TypeScript, Tailwind CSS)
- a **Next.js API route** backend (`POST /api/generate-workflow`)
- a **deterministic multi-agent pipeline** (no LLM required)
- an **optional LLM-assisted refinement layer** (OpenAI, off by default)
- an authenticated **tenant document corpus** (Markdown + plain text)
- a **report library** and interactive dashboard
- a **playbook / PDF export** page (print-ready A4)
- a **documents manager**
- **database-backed, tenant-scoped** report and document persistence (PostgreSQL)
- **authentication and multi-tenancy**, owned by the Python backend
- **no required external API key** (the LLM layer is optional; generation is
  deterministic without one)

The Python backend is **required**. It owns authentication, tenancy and
persistence, and authenticated routes have no fallback: with the backend
unreachable or `EVIDENTIA_BACKEND_URL` unset, they return **503**. Authenticated
reports live only in the database, never in `localStorage`. There is no anonymous
or browser-local generation route.

---

## How it works

When you select documents, a market, and a persona (or a custom role) and click **Run workflow**, Evidentia runs a deterministic multi-agent pipeline that turns static docs into a cited, persona-specific playbook:

```txt
Document Ingest → Persona Modeler → Semantic Retrieval → Risk Analyzer → Citation Binder → Metrics Agent → Playbook Composer
```

Each agent contributes one structured part of the final report — parsed sections, a persona brief, ranked evidence, risks, bound citations, metrics, and the assembled playbook. The pipeline runs in the Python backend, which authenticates the caller and persists the report to their organization.

---

## Deterministic vs. LLM-assisted mode

Evidentia ships with two interchangeable generation modes behind the same API and UI:

- **Deterministic (default).** With no LLM key configured, the pipeline is rule-based over the document corpus: reproducible, and requires **no API key**. (An API key is optional; the *backend* is not — it owns authentication and tenancy.)
- **LLM-assisted (optional).** With `OPENAI_API_KEY` set and `EVIDENTIA_USE_LLM=true`, LLM agents **refine** the deterministic baseline — improving persona modeling, workflows, risks, citations, and the report narrative. The deterministic output is always produced first and is used as the fallback for any step that fails.

Key guarantees:

- **Citations stay grounded** in the local document corpus — the citation agent only accepts source ids that exist in the analyzed sections, so evidence is never invented.
- **No keys are exposed client-side.** Secrets are read only in server code (`lib/env.ts`), never via `NEXT_PUBLIC_*`, and never returned in API responses.
- **The API never crashes.** If the LLM is disabled, misconfigured, or errors, each step falls back to deterministic output and the request still returns `200`.

Enable LLM mode:

```bash
cp .env.example .env.local
# then edit .env.local:
#   OPENAI_API_KEY=sk-...
#   EVIDENTIA_USE_LLM=true
```

Relevant env vars (see `.env.example`): `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `EVIDENTIA_LLM_PROVIDER`, `EVIDENTIA_LLM_MODEL`, `EVIDENTIA_USE_LLM`.

The report dashboard shows a **Deterministic** / **LLM-assisted** badge, and the agent timeline marks which agents were LLM-refined.

---

## Required Python backend

A parallel **FastAPI** implementation of the same pipeline lives in [`backend/`](./backend). It returns the identical `EvidentiaReport` JSON and can own the LLM keys server-side.

- The Next.js API route (`app/api/generate-workflow/route.ts`) is an authenticated **proxy** to the Python backend. It has **no fallback**: if the backend cannot validate the session, it returns 503 and generates nothing — a report on this route belongs to a real account and is persisted to that tenant.
- The frontend never sees API keys — the Python backend owns them.

Run the backend:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Point the frontend at it (repo root `.env.local`):

```
EVIDENTIA_BACKEND_URL=http://localhost:8000
```

The backend has three cost modes via `EVIDENTIA_LLM_INTENSITY`:

- **`off`** — deterministic only, no LLM calls (also used whenever no key is set).
- **`summary`** (default, recommended) — deterministic pipeline + **one** LLM call to polish the summary, top finding, and suggested actions.
- **`full`** — deterministic pipeline + up to **3** LLM calls; more expensive, for demos/testing.

The LLM only receives a compact, grounded **evidence pack** (never full documents in summary mode), outputs are token-capped and validated for precision, citations stay grounded in the local corpus, and repeated requests are cached in-memory. API keys live only in `backend/.env`.

Endpoints: `GET /health`, `GET /api/documents`, `POST /api/generate-workflow`. See [`backend/README.md`](./backend/README.md).

---

## Run locally

```bash
npm install
npm run dev
```

Then open **http://localhost:3000** and walk the flow:

1. `/` — landing page (nav links smooth-scroll to Product / Security / Docs / Pricing; "Sign in" opens the mock auth modal).
2. `/workspace` — select documents, a market, and a persona (or describe a custom role), then **Run workflow**.
3. `/running` — shows indeterminate backend progress, then redirects to the persisted report.
4. `/reports/[id]` — the persona-aware dashboard. Click **Export playbook (PDF)**.
5. `/playbook/[id]/print` — a dedicated 6-page A4 export preview. Click **Print / Save as PDF**.

Generated reports are persisted **in the database, scoped to your organization**, and re-fetched from the backend by id; `/reports`, `/playbooks`, and `/documents` list only authenticated tenant data. Nothing authenticated is cached in `localStorage`; browser storage is limited to versioned transient workspace/run input and is purged on session changes.

Production build:

```bash
npm run build
```

---

## Problem

Enterprise documentation is everywhere:

- security whitepapers
- API references
- deployment guides
- SLA commitments
- residency policies
- support runbooks
- pricing sheets
- onboarding handbooks
- compliance rules

But most documentation is static, generic, and difficult to apply in daily work.

A **Solutions Architect**, **Support Agent**, **Sales Engineer**, **Compliance Officer**, **Operations Manager**, **New Hire**, or **Field Technician** should not receive the same documentation experience.

They need different workflows, warnings, citations, metrics, and next actions.

---

## Solution

**Evidentia** turns static documentation into an interactive, persona-specific workspace.

Users can:

1. Select or upload company documents.
2. Select a market or region.
3. Select a persona or describe a custom role.
4. Run the authenticated backend workflow.
5. Generate a dashboard with key insights, risks, citations, and metrics.
6. Export the output as a clean persona-specific PDF playbook.

Instead of asking users to search through long documentation, Evidentia helps them understand what matters, what risks exist, what evidence supports the recommendation, and what to do next.

---

## Product Demo Flow

```txt
Landing page
   ↓
Create workspace
   ↓
Select documents
   ↓
Choose market
   ↓
Choose persona or custom role
   ↓
Run authenticated workflow
   ↓
Generated dashboard/report
   ↓
Export clean playbook PDF
```

The MVP is designed to feel like a real enterprise product, not a chatbot.

---

## Core Concept

Evidentia is not a single prompt over documents.

It is a structured **multi-agent documentation pipeline** where each agent owns one step of the transformation from static docs to an actionable playbook.

The system:

- ingests selected documents
- models the selected role and market
- retrieves relevant evidence
- detects role-specific risks
- synthesizes a persona brief
- binds recommendations to citations
- composes a final dashboard and exportable playbook

---

## 7-Agent Workflow

Evidentia runs a visible 7-stage pipeline:

```txt
1. Document Ingest Agent
2. Persona Modeler Agent
3. Semantic Retrieval Agent
4. Risk Analyzer Agent
5. Brief Synthesizer Agent
6. Citation Binder Agent
7. Playbook Composer Agent
```

### 1. Document Ingest Agent

Reads the selected enterprise documents and extracts structured sections, passages, metadata, and document type information.

Example output:

```txt
Parsed 3 documents into 489 passages.
```

### 2. Persona Modeler Agent

Builds a role profile from the selected persona, market, and optional custom role description.

For a **Solutions Architect**, it prioritizes:

- deployment topology
- data residency
- API surfaces
- rate limits
- failover design
- security review
- documented assumptions

For a **Support Agent**, it prioritizes:

- customer issue intake
- escalation paths
- approved responses
- refund boundaries
- privacy and security obligations

For a **Field Technician**, it can adapt to:

- on-site troubleshooting
- incident reporting
- equipment checks
- safety warnings
- escalation procedures

### 3. Semantic Retrieval Agent

Ranks and retrieves the most relevant passages for the selected persona and market.

For example:

```txt
"EMEA data residency" → Data Residency & Sovereignty Policy
"SLA failover" → SLA & Uptime Commitment
"API limits" → Platform API Reference
```

The MVP can use deterministic keyword/scoring logic first, with optional LLM enhancement later.

### 4. Risk Analyzer Agent

Identifies role-specific risks, warnings, gaps, and obligations.

Example risks:

```txt
Data residency gap for EMEA deployments
SLA credit terms undefined for multi-region outages
Incident runbook references a deprecated on-call tool
Pricing sheet omits egress overage tiers
```

### 5. Brief Synthesizer Agent

Creates a concise persona-specific brief that explains what matters for the selected role and market.

Example:

```txt
As a Solutions Architect, you turn requirements into resilient designs. This brief aligns the deployment guide, API surface, and residency policy so your reference architecture holds up to security review in the selected market.
```

### 6. Citation Binder Agent

Attaches every important recommendation, warning, or workflow step to source evidence.

Example citations:

```txt
SEC-4.2 — Security & Compliance Whitepaper
RES-14 — Data Residency & Sovereignty Policy
SLA-3 — SLA & Uptime Commitment
INC-2.1 — Incident Response Runbook
API-RL — Platform API Reference · Rate Limits
```

### 7. Playbook Composer Agent

Assembles the final output:

- persona brief
- dashboard metrics
- recommended workflow
- risks and warnings
- citations
- suggested actions
- exportable PDF playbook

---

## Input Documents

The tenant corpus accepts organization-owned Markdown and plain-text material such as:

```txt
Policies and standards
Operating procedures and runbooks
Technical reference notes
Enablement and onboarding guides
```

Documents are ingested, finalized and checked for generation eligibility before use.

---

## Markets

The user can select a market or region such as:

```txt
North America
EMEA
APAC
Public Sector / GovCloud
Financial Services
Healthcare
```

The selected market changes priorities, risks, and recommendations.

Example:

For **EMEA**, Evidentia prioritizes:

- data residency
- regional processing
- privacy obligations
- SLA terms
- compliant deployment topology

---

## Personas

The user can select a predefined persona such as:

```txt
Support Agent
Sales Engineer
Compliance Officer
Operations Manager
Solutions Architect
New Hire
```

The user can also describe a custom role:

```txt
Field technician handling on-site equipment incidents...
```

If a custom role is provided, Evidentia adapts the playbook to that role by inferring responsibilities, risks, workflows, and required citations.

---

## Dashboard Output

The final report dashboard includes:

### 1. Header

```txt
Persona Report · EMEA
Solutions Architect
Generated Jul 04 2026 · 7 agents · 3 docs · Confidence 92%
```

### 2. Metrics

Example:

```txt
Documents: 3
Passages indexed: 489
Citations: 11
Risks flagged: 4
Confidence: 92%
```

### 3. Persona Brief

A role-specific summary explaining the selected persona’s context and priorities.

### 4. Recommended Workflow

A practical step-by-step workflow adapted to the persona.

Example for a Solutions Architect:

```txt
1. Select deployment topology
2. Map required API surfaces
3. Design multi-region failover
4. Document assumptions
```

### 5. Risks & Warnings

Role-specific risks with severity levels and citations.

Example:

```txt
HIGH — Data residency gap for EMEA deployments
MED — SLA credit terms undefined for multi-region outages
MED — Incident runbook references a deprecated on-call tool
LOW — Pricing sheet omits egress overage tiers
```

### 6. Citations

Traceable source references that support the recommendations.

Example:

```txt
RES-14 — Data Residency & Sovereignty Policy · p.14
SLA-3 — SLA & Uptime Commitment · §3
DEP-11 — Deployment & Migration Guide · p.11
API-RL — Platform API Reference · Rate Limits
```

### 7. Document Relevance

Lightweight visual insight showing which documents mattered most.

Example:

```txt
Deployment Guide        98%
Security Whitepaper     70%
SLA Commitment          65%
```

### 8. Suggested Actions

Actionable next steps generated for the selected persona.

Example:

```txt
Generate a reference architecture brief
Validate residency topology
List API rate limits
Export full playbook
```

---

## Exportable Playbook PDF

The PDF export is not a raw print of the web dashboard.

Evidentia generates a dedicated print-friendly playbook layout without navigation, buttons, hover states, or dashboard-only UI controls.

The exportable playbook includes:

```txt
1. Cover header
2. Persona + market metadata
3. Executive summary
4. Key metrics
5. Persona brief
6. Recommended workflow
7. Risks and warnings
8. Source citations
9. Suggested next actions
```

For the hackathon MVP, this can be implemented as a dedicated print-friendly page such as:

```txt
/report/print
```

or:

```txt
/playbook
```

The export button opens the print layout and calls `window.print()`.

---

## Example Scenario

### Input

```txt
Company: Northreach Cloud
Market: EMEA
Persona: Solutions Architect

Selected documents:
- Security & Compliance Whitepaper
- SLA & Uptime Commitment
- Deployment & Migration Guide
```

### Output

```txt
Evidentia generated a persona-specific playbook for a Solutions Architect operating in EMEA.

The system identified deployment topology, data residency, SLA failover, and API limits as the most relevant areas.

It flagged 4 risks, attached 11 citations, and generated a workflow for building a compliant reference architecture.
```

---

## What Makes Evidentia Different

| Static Documentation | Evidentia |
|---|---|
| Same content for everyone | Persona-specific workflows |
| Search-based | Action-based |
| Long documents | Interactive workspace |
| Generic guidance | Role-aware recommendations |
| No clear next step | Suggested actions |
| No traceability | Source citations |
| No metrics | Dashboard insights |
| Manual interpretation | 7-agent workflow |
| Hard to share | Exportable PDF playbook |

---

## Tech Stack

```txt
Frontend:  Next.js (App Router), TypeScript, Tailwind CSS
BFF:       Next.js API routes — hold httpOnly session cookies, proxy to the backend
Backend:   Python FastAPI (required) — authentication, tenancy, persistence
Pipeline:  Deterministic multi-agent orchestrator + optional LLM refinement (OpenAI)
Storage:   PostgreSQL (managed, in production). SQLite is local development ONLY.
Auth:      Email + password; JWT access tokens + rotating refresh tokens
Deployment: Vercel (frontend) + a container host (backend)
```

The pipeline runs deterministically with no API key. The Python backend is required in all cases: it owns authentication, tenant isolation and persistence.

---

## Repository Structure

```txt
evidentia/
├── app/
│   ├── api/
│   │   └── generate-workflow/
│   │       └── route.ts          # POST — runs the multi-agent pipeline
│   ├── documents/
│   │   └── page.tsx              # /documents — corpus manager
│   ├── playbook/
│   │   └── [id]/
│   │       └── print/
│   │           └── page.tsx      # /playbook/[id]/print — A4 PDF export
│   ├── playbooks/
│   │   └── page.tsx              # /playbooks — playbook library
│   ├── reports/
│   │   ├── [id]/
│   │   │   └── page.tsx          # /reports/[id] — interactive dashboard
│   │   └── page.tsx              # /reports — reports library
│   ├── running/
│   │   └── page.tsx              # /running — indeterminate backend progress
│   ├── workspace/
│   │   └── page.tsx              # /workspace — configuration flow
│   ├── globals.css               # theme + print CSS
│   ├── layout.tsx
│   └── page.tsx                  # / — landing page
├── components/
│   ├── AppShell.tsx
│   ├── AppSidebar.tsx
│   ├── AuthModal.tsx
│   ├── Logo.tsx
│   ├── SettingsModal.tsx
│   ├── SignInForm.tsx
│   └── SignUpForm.tsx
├── lib/
│   ├── tenantDocuments.ts        # authenticated tenant document API state
│   ├── reportsApi.ts             # persisted tenant report API reads
│   ├── workflowGeneration.ts     # authenticated single-flight generation
│   ├── workspaceMapping.ts       # tenant selection → backend input
│   ├── pendingRun.ts             # versioned transient run input
│   ├── types.ts
│   ├── personas.ts
│   ├── markets.ts
│   ├── scenarios.ts              # report categories + playbook templates
│   ├── useSettings.ts
│   └── useWorkspace.ts
├── backend/                      # required Python FastAPI backend
│   ├── app/
│   │   ├── main.py               # FastAPI app (health, documents, generate)
│   │   ├── core/
│   │   │   └── config.py         # pydantic-settings config (owns keys)
│   │   ├── models/
│   │   │   └── schemas.py
│   │   ├── agents/
│   │   │   ├── orchestrator.py
│   │   │   ├── document_reader.py
│   │   │   ├── persona_mapper.py
│   │   │   ├── workflow_builder.py
│   │   │   ├── risk_analyzer.py
│   │   │   ├── citation_binder.py
│   │   │   ├── metrics_agent.py
│   │   │   └── report_composer.py
│   │   ├── tools/
│   │   │   ├── document_search.py
│   │   │   ├── citation_tools.py
│   │   │   ├── risk_tools.py
│   │   │   └── scoring_tools.py
│   │   ├── services/
│   │   │   └── llm.py            # OpenAI wrapper (server-only, safe fallback)
│   │   └── data/
│   │       └── documents/        # backend benchmark fixtures
│   ├── requirements.txt
│   ├── .env.example
│   └── README.md
├── public/
│   └── evidentia-logo.png
├── .env.example
├── next.config.mjs
├── postcss.config.mjs
├── tailwind.config.ts
├── tsconfig.json
├── package.json
└── README.md
```

---

## MVP Scope

For the hackathon MVP, the goal is a functional product demo, not a production-ready enterprise platform.

The MVP should include:

- premium landing page
- workspace configuration screen
- document selection
- market selection
- persona selection
- custom role input
- honest indeterminate running screen
- generated dashboard report
- source citations
- risk cards
- dashboard metrics
- document relevance chart
- suggested actions
- print-friendly playbook export
- Vercel deployment

The core workflow uses finalized tenant data and deterministic logic, with optional LLM refinement.

---

## Implementation Philosophy

Honest and practical:

- deterministic agents for reliability
- optional LLM calls for synthesis (generation works with no API key)
- authentication, tenancy and persistence owned by the backend — **required**, with
  no degraded mode: authenticated routes return 503 rather than inventing a session
  or a report
- managed PostgreSQL in production (SQLite is local development only)
- no real RAG infrastructure required for the MVP
- clean modular architecture
- polished UI first
- tenant workflow end-to-end through the authenticated backend, with no local
  evidence or generation fallback

This is a hackathon MVP showing the core interaction:

```txt
Tenant docs → selected role + market → backend pipeline → dashboard → exportable playbook
```

---

## Future Vision

Evidentia could become a documentation intelligence layer for enterprise teams.

Future features could include:

- Notion integration
- Confluence integration
- Google Drive integration
- Slack integration
- GitHub documentation sync
- automatic persona detection
- team onboarding mode
- compliance review mode
- policy drift detection
- real semantic retrieval
- vector database support
- voice-based documentation assistant
- live documentation updates
- analytics on documentation usage

---

## Tagline

**Evidentia turns static company documentation into persona-specific workflows and exportable playbooks.**
