# Evidentia

Evidentia is an enterprise agent for evidence-backed operational investigations.

Built for the Vultr Enterprise Agent track, Evidentia helps manufacturing quality teams investigate incidents by analyzing production KPI reports, maintenance logs, and quality procedures.

## Agent workflow

1. Plan investigation
2. Parse operational documents
3. Run anomaly detection tools
4. Retrieve evidence from logs and procedures
5. Generate root-cause hypotheses
6. Produce a cited corrective action report

## Tech stack

- Frontend: Next.js, Tailwind, shadcn/ui
- Backend: FastAPI, Python, pandas
- AI: Claude/GPT first, Vultr Serverless Inference later
- Infrastructure: Vultr Cloud Compute, Vultr Object Storage, Vultr Serverless Inference

## Demo flow

Upload:
- Production KPI Report
- Maintenance Logs
- Quality Procedure

Then Evidentia generates:
- Agent timeline
- Detected anomalies
- Evidence citations
- Root-cause hypotheses
- Confidence scores
- Corrective action plan
