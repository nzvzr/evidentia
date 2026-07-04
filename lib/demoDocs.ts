import type { DemoDoc, DocId } from "./types";

export const DEMO_DOCS: DemoDoc[] = [
  {
    id: "d1",
    name: "Security & Compliance Whitepaper",
    short: "Security Whitepaper",
    meta: "PDF · 48 pages · updated 12 days ago",
    kind: "PDF",
    description: "Encryption, access controls, and certification posture.",
    base: 70,
  },
  {
    id: "d2",
    name: "Platform API Reference",
    short: "API Reference",
    meta: "HTML · 320 endpoints · versioned",
    kind: "HTML",
    description: "Endpoints, authentication, and rate limits.",
    base: 60,
  },
  {
    id: "d3",
    name: "SLA & Uptime Commitment",
    short: "SLA Commitment",
    meta: "PDF · 12 pages · legal-reviewed",
    kind: "PDF",
    description: "Availability targets, remedies, and credit terms.",
    base: 65,
  },
  {
    id: "d4",
    name: "Deployment & Migration Guide",
    short: "Deployment Guide",
    meta: "PDF · 86 pages · engineering",
    kind: "PDF",
    description: "Topologies, rollout patterns, and rollback.",
    base: 68,
  },
  {
    id: "d5",
    name: "Data Residency & Sovereignty Policy",
    short: "Residency Policy",
    meta: "PDF · 24 pages · compliance",
    kind: "PDF",
    description: "Regional processing and data-locality rules.",
    base: 62,
  },
  {
    id: "d6",
    name: "Incident Response Runbook",
    short: "Incident Runbook",
    meta: "Markdown · 31 pages · on-call",
    kind: "MD",
    description: "Severity matrix, escalation, and on-call paths.",
    base: 64,
  },
  {
    id: "d7",
    name: "Pricing & Packaging Sheet",
    short: "Pricing Sheet",
    meta: "XLSX · 5 tabs · revenue ops",
    kind: "XLSX",
    description: "Tiers, add-ons, and overage structures.",
    base: 45,
  },
  {
    id: "d8",
    name: "Customer Onboarding Handbook",
    short: "Onboarding Handbook",
    meta: "PDF · 40 pages · enablement",
    kind: "PDF",
    description: "Ramp path, roles, and platform basics.",
    base: 40,
  },
];

export const DEFAULT_PICKED: DocId[] = ["d1", "d3", "d4", "d8"];

export function getDoc(id: DocId): DemoDoc | undefined {
  return DEMO_DOCS.find((d) => d.id === id);
}
