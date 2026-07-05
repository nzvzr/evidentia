/**
 * Isomorphic mirror of data/documents/*.md.
 *
 * The markdown files are the human-readable source of truth. This map holds
 * the same content as strings so the Document Reader Agent can parse it on the
 * server (API route) and on the client (deterministic fallback) without a
 * filesystem dependency. Keep these in sync with the .md files.
 */
export const DOCUMENT_CONTENT: Record<string, string> = {
  "security-compliance-whitepaper": `# Security & Compliance Whitepaper

## Encryption
All customer data is encrypted at rest using AES-256 and in transit via TLS 1.3.

## Access Control
Administrative access requires multi-factor authentication and role-based authorization.

## Audit Logging
Security-relevant actions are logged and retained for audit review.

## Customer Responsibilities
Customers must configure identity policies and restrict privileged access.
`,
  "platform-api-reference": `# Platform API Reference

## Authentication
API access requires scoped tokens with least-privilege permissions.

## Rate Limits
Default account limit is 2,000 requests per minute, burstable to 5,000.

## Error Handling
Clients should implement retry with exponential backoff for transient failures.

## Webhooks
Webhook delivery is retried for 24 hours before being marked failed.
`,
  "sla-uptime-commitment": `# SLA & Uptime Commitment

## Availability
Northreach commits to 99.99% monthly availability for multi-AZ Enterprise deployments.

## Service Credits
Service credits apply only when the customer submits a claim within 30 days of the incident.

## Exclusions
Scheduled maintenance and customer misconfiguration are excluded from SLA calculations.

## Escalation
Severity 1 incidents require immediate escalation to the primary on-call owner.
`,
  "deployment-migration-guide": `# Deployment & Migration Guide

## Deployment Topology
Blue-green deployments are supported across all commercial regions with automated rollback.

## Multi-region Failover
Customers requiring regional redundancy must validate data replication and failover objectives.

## Migration Checklist
Production migration requires dependency inventory, rollback plan, and stakeholder approval.

## Rollback
Rollback procedures must be tested before migration windows.
`,
  "data-residency-sovereignty-policy": `# Data Residency & Sovereignty Policy

## EMEA Processing
Default control-plane metadata is processed in us-east-1 unless in-region processing is provisioned.

## Regulated Workloads
Regulated workloads require residency review before production onboarding.

## Sovereign Cloud
Sovereign cloud deployments require explicit approval from the compliance team.

## Data Export
Customer data exports must follow approved access and retention procedures.
`,
  "incident-response-runbook": `# Incident Response Runbook

## Severity Classification
Severity 1 incidents page the primary on-call within 5 minutes via the escalation tool.

## Customer Communication
Customer-facing incident updates must use approved communication templates.

## Escalation Path
Unresolved Severity 1 incidents escalate to the incident commander after 15 minutes.

## Deprecated Tool Notice
PagerTree references are deprecated and must be replaced with the current on-call routing system.
`,
  "pricing-packaging-sheet": `# Pricing & Packaging Sheet

## Plan Tiers
Enterprise plans include premium support, multi-AZ deployment, and advanced compliance controls.

## Usage Limits
Customers must be informed of usage limits before purchase or renewal.

## Overage
Egress overage tiers require finance approval and must be documented in the customer order.

## Discount Approval
Discounts above 15% require revenue operations approval.
`,
  "customer-onboarding-handbook": `# Customer Onboarding Handbook

## Kickoff
Customer kickoff must confirm success criteria, stakeholders, and target launch date.

## Technical Validation
Technical validation requires confirming identity, networking, API, and deployment requirements.

## Training
Customer teams must receive role-specific training before go-live.

## Go-live Review
Go-live requires sign-off from customer owner, technical owner, and support readiness lead.
`,
};
