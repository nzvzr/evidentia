# Evidentia

**Evidentia** is a persona-aware documentation agent that transforms static enterprise documentation into role-specific workflows, risk insights, traceable citations, dashboard metrics, and exportable playbooks.

Built for the **RAISE Summit Hackathon**.

> Static documentation is written once, but every team uses it differently. Evidentia turns scattered company docs into actionable playbooks adapted to each role, market, and business context.

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
4. Run a visible 7-agent workflow.
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
Run 7-agent workflow
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

The MVP can work with demo enterprise documents such as:

```txt
Security & Compliance Whitepaper
Platform API Reference
SLA & Uptime Commitment
Deployment & Migration Guide
Data Residency & Sovereignty Policy
Incident Response Runbook
Pricing & Packaging Sheet
Customer Onboarding Handbook
```

These simulate scattered internal documentation used by enterprise teams.

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
Frontend: Next.js, TypeScript, Tailwind CSS, shadcn/ui
Backend: Next.js API routes
AI: GPT / Claude with deterministic fallback
Deployment: Vercel
Development: Cursor / Claude / GPT
```

The MVP works with demo data first and can later connect to real enterprise documentation sources.

---

## Repository Structure

```txt
evidentia/
  README.md
  .env.example
  .gitignore

  app/
    layout.tsx
    page.tsx
    workspace/
      page.tsx
    running/
      page.tsx
    report/
      page.tsx
    playbook/
      page.tsx
    api/
      generate-workflow/
        route.ts

  components/
    Logo.tsx
    UploadDocs.tsx
    MarketSelector.tsx
    PersonaSelector.tsx
    CustomRoleInput.tsx
    AgentTimeline.tsx
    MetricsDashboard.tsx
    PersonaBrief.tsx
    WorkflowSteps.tsx
    RiskCard.tsx
    CitationPanel.tsx
    DocumentRelevanceChart.tsx
    SuggestedActions.tsx
    ExportPlaybookButton.tsx
    PlaybookLayout.tsx

  lib/
    demoDocs.ts
    demoReport.ts
    markets.ts
    personas.ts
    prompt.ts
    types.ts
    agents/
      orchestrator.ts
      documentIngestAgent.ts
      personaModelerAgent.ts
      semanticRetrievalAgent.ts
      riskAnalyzerAgent.ts
      briefSynthesizerAgent.ts
      citationBinderAgent.ts
      playbookComposerAgent.ts

  demo-data/
    security_compliance_whitepaper.md
    platform_api_reference.md
    sla_uptime_commitment.md
    deployment_migration_guide.md
    data_residency_policy.md
    incident_response_runbook.md
    pricing_packaging_sheet.md
    customer_onboarding_handbook.md

  public/
    logo.png
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
- visible 7-agent running screen
- generated dashboard report
- source citations
- risk cards
- dashboard metrics
- document relevance chart
- suggested actions
- print-friendly playbook export
- Vercel deployment

The core workflow should work with demo data and deterministic logic, with optional GPT/Claude enhancement.

---

## Implementation Philosophy

The prototype should be honest and practical:

- deterministic agents for reliability
- optional LLM calls for synthesis
- no database required
- no authentication required
- no real RAG infrastructure required for the MVP
- clean modular architecture
- polished UI first
- demo flow end-to-end

This is a hackathon MVP showing the core interaction:

```txt
Static docs → selected role + market → 7-agent pipeline → dashboard → exportable playbook
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
