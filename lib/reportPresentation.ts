import type { EvidentiaReport, ReportClaimAudit } from "./types";

export interface ClaimDecisionCounts {
  accepted: number;
  rejected: number;
  insufficient: number;
}

export function claimDecisionCounts(audit: ReportClaimAudit | null): ClaimDecisionCounts {
  const counts = { accepted: 0, rejected: 0, insufficient: 0 };
  for (const candidate of audit?.candidates ?? []) {
    const status = candidate.decision?.status;
    if (status === "accepted") counts.accepted += 1;
    else if (status === "rejected") counts.rejected += 1;
    else if (status === "insufficient_evidence") counts.insufficient += 1;
  }
  return counts;
}

/**
 * A zero-claim presentation is only valid for a persisted M5a run whose
 * structured decision audit has no accepted claims and whose complete
 * analytical projection is empty. Narrative wording and confidence are never
 * used to infer this state.
 */
export function hasZeroAcceptedAnalyticalOutput(
  report: EvidentiaReport,
  audit: ReportClaimAudit | null,
): boolean {
  return Boolean(
    audit?.claimEngineEnabled
      && claimDecisionCounts(audit).accepted === 0
      && hasEmptyAnalyticalProjection(report),
  );
}

export function hasEmptyAnalyticalProjection(report: EvidentiaReport): boolean {
  return report.workflowSteps.length === 0
    && report.risks.length === 0
    && report.suggestedActions.length === 0;
}
