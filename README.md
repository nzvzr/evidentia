# Evidentia

**Evidentia** is a persona-aware documentation agent that transforms static enterprise documentation into interactive workflows, dashboards, metrics, citations, and exportable playbooks for specific roles and markets.

Built for the **RAISE Summit Hackathon**.

> Static documentation is written once, but every team uses it differently. Evidentia turns scattered company docs into role-specific workflows, cited recommendations, risk insights, and actionable playbooks.

---

## Problem

Companies produce a lot of internal documentation:

- support processes
- product policies
- compliance rules
- onboarding guides
- sales playbooks
- operational procedures
- technical manuals

But most documentation is static, generic, and difficult to apply in daily work.

A support agent, sales representative, compliance officer, operations manager, and new employee should not experience the same documentation in the same way.

They need different workflows, warnings, metrics, citations, and next actions.

---

## Solution

**Evidentia** turns static documentation into an interactive, persona-specific workspace.

Users can:

1. Upload or use demo company documentation.
2. Select a market or industry.
3. Select a persona.
4. Generate a personalized workflow.
5. View a dashboard with key insights, risks, citations, and stats.
6. Export the result as a persona-specific PDF playbook.

Instead of asking users to search through documentation, Evidentia helps them understand what matters and what to do next.

---

## Core Concept

Evidentia is not a chatbot.

It is a multi-agent documentation system that:

- reads multiple company documents
- understands the selected persona
- adapts the output to the selected market
- extracts relevant workflows
- identifies risks and obligations
- generates role-specific actions
- cites the source documents
- produces a dashboard and exportable report

---

## Demo Flow

1. User lands on Evidentia.
2. User opens the workspace.
3. User uploads or uses demo documentation.
4. User selects a market.
5. User selects a persona.
6. Evidentia runs a visible multi-agent workflow.
7. Evidentia generates an interactive dashboard.
8. User exports a persona-specific PDF playbook.

---

## Input Documents

The MVP uses four demo documents:

- `support_process.md`
- `product_policy.md`
- `compliance_rules.md`
- `onboarding_guide.md`

These simulate scattered internal documentation used by enterprise teams every day.

---

## Markets

The user can select a market such as:

- SaaS
- Finance
- Healthcare
- Manufacturing
- Hospitality
- Telecommunications

The selected market changes the priorities, risks, and recommended workflow.

---

## Personas

The user can select a persona such as:

- Support Agent
- Sales Representative
- Compliance Officer
- Operations Manager
- New Employee
- Field Technician

Each persona receives a different workspace based on what they actually need to do.

---

## Multi-Agent Workflow

Evidentia runs a structured multi-agent pipeline:

1. Document Reader Agent
2. Persona Mapper Agent
3. Workflow Builder Agent
4. Risk Agent
5. Citation Agent
6. Metrics Agent
7. Report Agent

### Document Reader Agent

Reads the uploaded or demo documentation, splits it into sections, and extracts useful knowledge chunks.

### Persona Mapper Agent

Maps the documentation to the selected persona and market.

For a **Support Agent**, it prioritizes:

- escalation paths
- refund rules
- customer communication
- privacy obligations
- approved response guidelines

For a **Sales Representative**, it prioritizes:

- product claims
- positioning
- pricing boundaries
- compliance-safe language

### Workflow Builder Agent

Transforms documentation into practical step-by-step workflows.

### Risk Agent

Detects persona-specific risks, warnings, and obligations.

### Citation Agent

Connects recommendations, risks, and workflow steps to source documents.

### Metrics Agent

Generates dashboard metrics such as:

- documents analyzed
- relevant sections found
- citations used
- risk warnings
- workflow steps generated
- persona relevance score
- workflow completeness
- citation coverage
- compliance sensitivity

### Report Agent

Assembles the final interactive dashboard and exportable playbook.

---

## Final Output

At the end of the flow, Evidentia generates an interactive dashboard with:

### Persona Brief

A short summary of what matters for the selected role.

Example:

**As a Support Agent, your main objective is to resolve customer issues quickly while respecting escalation, refund, privacy, and compliance rules.**

### Workflow Steps

A clear step-by-step workflow adapted to the persona.

Example:

1. Identify the customer issue category.
2. Check whether the issue matches an approved support path.
3. Use the approved response guideline.
4. Verify refund eligibility before promising compensation.
5. Escalate privacy, billing, or legal issues.

### Risk & Warning Cards

Role-specific risks extracted from the documentation.

Example:

- Do not promise compensation outside the approved refund policy.
- Escalate privacy-related requests immediately.
- Do not share internal debugging steps with customers.

### Source Citations

Every important recommendation is backed by a source.

Example:

- `support_process.md` — Escalation section
- `product_policy.md` — Refund policy
- `compliance_rules.md` — Privacy obligations

### Dashboard Metrics

Example metrics:

- Documents analyzed: 4
- Relevant sections found: 12
- Citations used: 8
- Risk warnings: 5
- Workflow steps generated: 6
- Persona relevance score: 91%
- Compliance sensitivity: High

### Visual Insights

The MVP displays lightweight visualizations such as:

- relevance by document
- citation coverage
- risk breakdown
- workflow completeness
- compliance sensitivity

Example document relevance:

| Document | Relevance |
|---|---:|
| support_process.md | 92% |
| product_policy.md | 78% |
| compliance_rules.md | 85% |
| onboarding_guide.md | 41% |

### Suggested Next Actions

Example:

- Use the approved customer response template.
- Create an internal escalation ticket.
- Ask compliance to review the case if privacy concerns are involved.
- Export this workflow as a team playbook.

---

## PDF Export

Evidentia can export the generated workspace as a persona-specific PDF playbook.

The PDF includes:

1. Executive Summary
2. Selected Market
3. Selected Persona
4. Role-Specific Workflow
5. Key Risks and Warnings
6. Dashboard Metrics
7. Source Citations
8. Recommended Next Actions

For the MVP, PDF export can be implemented using a print-friendly report page or a simple `window.print()` export button.

---

## Example Scenario

### Input

Market: **SaaS**  
Persona: **Support Agent**

Documents:

- `support_process.md`
- `product_policy.md`
- `compliance_rules.md`
- `onboarding_guide.md`

### Output

Persona: **Support Agent**

Main objective:

Resolve customer issues efficiently while respecting support, refund, privacy, and escalation policies.

Recommended workflow:

1. Identify the customer issue.
2. Check whether the issue matches an approved support path.
3. Use the approved customer response.
4. Verify refund eligibility.
5. Escalate privacy, legal, or billing issues.

Risks:

- Do not promise compensation outside the refund policy.
- Do not expose internal troubleshooting details.
- Escalate privacy-related requests immediately.

Citations:

- `support_process.md` — Escalation section
- `product_policy.md` — Refund policy
- `compliance_rules.md` — Privacy obligations

Dashboard:

- Documents analyzed: 4
- Relevant sections: 12
- Citations used: 8
- Risk warnings: 5
- Persona relevance score: 91%

---

## What Makes Evidentia Different

| Static Documentation | Evidentia |
|---|---|
| Same content for everyone | Persona-specific workflows |
| Search-based | Action-based |
| Long documents | Interactive workspace |
| Generic guidance | Role-aware recommendations |
| No clear next step | Suggested actions |
| No metrics | Dashboard insights |
| Hard to share | Exportable PDF playbook |
| Manual interpretation | Multi-agent workflow |

---

## Tech Stack

- Frontend: Next.js, TypeScript, Tailwind CSS, shadcn/ui
- Backend: Next.js API routes
- AI: GPT / Claude with deterministic fallback
- Deployment: Vercel
- Development: Claude / GPT / VS Code

The MVP is designed to work with demo data first, then connect to external APIs if needed.

---

## Repository Structure

```txt
evidentia/
  README.md
  .env.example

  app/
    page.tsx
    workspace/
      page.tsx
    report/
      page.tsx
    api/
      generate-workflow/
        route.ts

  components/
    Logo.tsx
    UploadDocs.tsx
    MarketSelector.tsx
    PersonaSelector.tsx
    AgentTimeline.tsx
    PersonaWorkspace.tsx
    WorkflowSteps.tsx
    RiskCard.tsx
    CitationPanel.tsx
    MetricsDashboard.tsx
    DocumentRelevanceChart.tsx
    ExportPDFButton.tsx
    PlaybookPreview.tsx

  lib/
    demoDocs.ts
    demoReport.ts
    markets.ts
    personas.ts
    prompt.ts
    types.ts
    agents/
      orchestrator.ts
      documentReaderAgent.ts
      personaMapperAgent.ts
      workflowBuilderAgent.ts
      riskAgent.ts
      citationAgent.ts
      metricsAgent.ts
      reportAgent.ts

  demo-data/
    support_process.md
    product_policy.md
    compliance_rules.md
    onboarding_guide.md

  public/
    logo.png
```

---

## MVP Goals

For the hackathon MVP, we focus on:

- clean landing page
- document upload or demo document mode
- market selection
- persona selection
- visible multi-agent timeline
- generated persona workspace
- workflow steps
- risk cards
- source citations
- dashboard metrics
- lightweight visual insights
- exportable PDF or print-friendly report page
- Vercel deployment

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
- voice-based documentation assistant
- real-time documentation updates
- analytics on documentation usage

---

## Tagline

**Evidentia turns static company documentation into persona-specific workflows.**
