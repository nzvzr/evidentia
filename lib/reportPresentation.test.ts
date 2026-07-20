import { describe, expect, it } from "vitest";
import type { EvidentiaReport, ReportClaimAudit } from "./types";
import { claimDecisionCounts, hasZeroAcceptedAnalyticalOutput } from "./reportPresentation";

const report = {
  workflowSteps: [],
  risks: [],
  suggestedActions: [],
} as unknown as EvidentiaReport;

const audit: ReportClaimAudit = {
  claimEngineEnabled: true,
  candidates: [
    { candidateId: "rejected", appearedInFinal: false, decision: { status: "rejected" } },
    { candidateId: "insufficient", appearedInFinal: false, decision: { status: "insufficient_evidence" } },
  ],
};

describe("zero accepted analytical output", () => {
  it("requires a persisted M5a audit and all analytical arrays to be empty", () => {
    expect(hasZeroAcceptedAnalyticalOutput(report, audit)).toBe(true);
    expect(hasZeroAcceptedAnalyticalOutput(report, null)).toBe(false);
    expect(hasZeroAcceptedAnalyticalOutput({ ...report, workflowSteps: [{}] } as EvidentiaReport, audit)).toBe(false);
  });

  it("does not classify a report with an accepted decision as zero claim", () => {
    const accepted = {
      ...audit,
      candidates: [{ candidateId: "accepted", appearedInFinal: true, decision: { status: "accepted" } }],
    };
    expect(hasZeroAcceptedAnalyticalOutput(report, accepted)).toBe(false);
    expect(claimDecisionCounts(audit)).toEqual({ accepted: 0, rejected: 1, insufficient: 1 });
  });
});
