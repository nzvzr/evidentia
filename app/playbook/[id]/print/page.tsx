"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import Logo from "@/components/Logo";
import { fetchBackendReport, fetchReportClaimAudit, fetchReportSourceAudit } from "@/lib/reportsApi";
import { claimDecisionCounts, hasZeroAcceptedAnalyticalOutput } from "@/lib/reportPresentation";
import type { EvidentiaReport, ReportClaimAudit, ReportSourceAudit, RiskItem } from "@/lib/types";

const mono = "var(--font-plex-mono), monospace";

const SEV_COLORS: Record<RiskItem["severity"], string> = {
  High: "#c34635",
  Medium: "#c1852b",
  Low: "#8b8b91",
};

const INSUFFICIENT = "N/A";
const isInsufficient = (code: string) => (code || "").trim().toUpperCase() === INSUFFICIENT;

function formatStamp(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const mon = d.toLocaleString("en-US", { month: "short", timeZone: "UTC" }).toUpperCase();
  const day = String(d.getUTCDate()).padStart(2, "0");
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${mon} ${day} ${d.getUTCFullYear()} · ${hh}:${mm} UTC`;
}

export default function PrintPlaybookPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const id = (Array.isArray(params.id) ? params.id[0] : params.id) || "current";

  const [report, setReport] = useState<EvidentiaReport | null>(null);
  const [sourceAudit, setSourceAudit] = useState<ReportSourceAudit | null>(null);
  const [claimAudit, setClaimAudit] = useState<ReportClaimAudit | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [backendReport, audit, claims] = await Promise.all([
        fetchBackendReport(id),
        fetchReportSourceAudit(id),
        fetchReportClaimAudit(id),
      ]);
      if (cancelled) return;
      // Backend only. Never fall back to a cached/generated report: printing a
      // fabricated or another tenant's report as an official playbook is worse
      // than printing nothing.
      setReport(backendReport);
      setSourceAudit(audit);
      setClaimAudit(claims);
    })();
    try {
      window.scrollTo(0, 0);
    } catch {
      /* ignore */
    }
    return () => {
      cancelled = true;
    };
  }, [id]);

  // Backend-only: until the report is loaded (or if it does not exist for this
  // tenant) there is nothing legitimate to print.
  if (!report) {
    return (
      <div style={{ padding: 48, fontFamily: "var(--font-archivo), sans-serif" }}>
        <h1 style={{ fontSize: 20, fontWeight: 700, margin: 0 }}>Report unavailable</h1>
        <p style={{ fontSize: 13.5, color: "#666", marginTop: 8 }}>
          This playbook could not be loaded. It may not exist, or it may belong to a different
          organization.
        </p>
      </div>
    );
  }

  const { metrics } = report;
  const zeroClaims = hasZeroAcceptedAnalyticalOutput(report, claimAudit);
  const allowReportCitationFallback = sourceAudit?.corpusMode === "demo";
  const mode = report.generationMode ?? "deterministic";
  const counts = {
    High: report.risks.filter((r) => r.severity === "High").length,
    Medium: report.risks.filter((r) => r.severity === "Medium").length,
    Low: report.risks.filter((r) => r.severity === "Low").length,
  };
  const totalRisks = report.risks.length;

  const metricCards = [
    { k: "DOCUMENTS", v: String(metrics.documentsAnalyzed), accent: false },
    { k: "CITATIONS", v: String(metrics.citationsUsed), accent: false },
    { k: "RISKS", v: String(metrics.risksFlagged), accent: false },
    { k: "WORKFLOW STEPS", v: String(report.workflowSteps.length), accent: false },
    { k: "BASELINE SCORE", v: `${report.confidence}%`, accent: false },
  ];

  return (
    <div style={{ minHeight: "100vh", background: "#d7d7d3" }}>
      {/* toolbar (hidden on print) */}
      <div className="no-print" style={{ position: "sticky", top: 0, zIndex: 10, display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 28px", height: 56, background: "var(--paper)", borderBottom: "1px solid var(--line)" }}>
        <button onClick={() => router.push(`/reports/${report.id}`)} style={{ fontFamily: "inherit", fontSize: 13, fontWeight: 500, color: "var(--ink)", background: "transparent", border: "none", cursor: "pointer", display: "flex", alignItems: "center", gap: 8 }}>
          ← Back to report
        </button>
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <span style={{ fontFamily: mono, fontSize: 11, color: "var(--sub)" }}>EXPORT PREVIEW · EXECUTIVE PLAYBOOK</span>
          <button onClick={() => window.print()} style={{ fontFamily: "inherit", fontSize: 13, fontWeight: 600, color: "#fff", background: "#0a0a0b", border: "none", padding: "9px 16px", borderRadius: 8, cursor: "pointer" }}>
            Print / Save as PDF
          </button>
        </div>
      </div>

      <div className="print-shell">
        {zeroClaims ? (
          <ZeroClaimPrint
            report={report}
            sourceAudit={sourceAudit}
            counts={claimDecisionCounts(claimAudit)}
          />
        ) : <>
        {/* ===== PAGE 1 · COVER / EXECUTIVE SUMMARY ===== */}
        <section className="print-page">
          <div className="page-content">
            <PageHeader report={report} confidential showMeta={false} />
            <div style={{ marginTop: 44 }}>
              <div style={{ fontFamily: mono, fontSize: 11, color: "var(--accent)", letterSpacing: ".16em", textTransform: "uppercase" }}>Persona Playbook</div>
              <h1 style={{ fontSize: 48, fontWeight: 700, letterSpacing: "-.03em", lineHeight: 1, margin: "14px 0 0" }}>{report.persona}</h1>
              <div style={{ fontSize: 15, color: "var(--sub)", marginTop: 12 }}>{report.company} — {report.market} market</div>
              <div style={{ fontFamily: mono, fontSize: 10, color: "var(--sub)", letterSpacing: ".08em", marginTop: 8 }}>
                GENERATION · {mode === "deterministic" ? "DETERMINISTIC" : `${mode === "llm-summary" ? "LLM-SUMMARY" : "LLM-ASSISTED"}${report.llmModel ? ` · ${report.llmModel}` : ""}`}
              </div>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(5,1fr)", border: "1px solid var(--line2)", borderRadius: 9, overflow: "hidden", marginTop: 30 }}>
              <MetaCell label="COMPANY" value={report.company} />
              <MetaCell label="MARKET" value={report.market} />
              <MetaCell label="PERSONA" value={report.persona} />
              <MetaCell label="GENERATED" value={formatStamp(report.generatedAt)} mono />
              <div style={{ padding: "15px 16px" }}>
                <div style={metaLabel}>BASELINE SCORE</div>
                <div style={{ fontSize: 22, fontWeight: 700, marginTop: 3, letterSpacing: "-.02em" }}>{report.confidence}%</div>
              </div>
            </div>

            <div style={{ marginTop: 36 }}>
              <SectionTitle>01 · EXECUTIVE SUMMARY</SectionTitle>
              <p style={{ fontSize: 14.5, lineHeight: 1.7, color: "var(--ink2)", margin: 0 }}>{report.summary}</p>
            </div>

            <div style={{ marginTop: 22, padding: "16px 18px", border: "1px solid var(--line2)", borderRadius: 9, background: "var(--accent-weak)" }}>
              <div style={{ fontFamily: mono, fontSize: 9.5, color: "var(--accent)", letterSpacing: ".1em", fontWeight: 600 }}>TOP FINDING</div>
              <div style={{ fontSize: 14.5, fontWeight: 600, color: "var(--ink)", marginTop: 7, lineHeight: 1.5 }}>{report.topFinding}</div>
            </div>

            {report.suggestedActions.length > 0 && <div style={{ marginTop: 32 }}>
              <SectionTitle>02 · TOP RECOMMENDATIONS</SectionTitle>
              {report.suggestedActions.slice(0, 3).map((a, i) => (
                <div key={a.title} style={{ display: "flex", gap: 16, padding: "15px 0", borderBottom: i < 2 ? "1px solid var(--line)" : "none" }}>
                  <span style={{ fontFamily: mono, fontSize: 13, fontWeight: 600, color: "var(--accent)" }}>{String(i + 1).padStart(2, "0")}</span>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 14.5, fontWeight: 600, color: "var(--ink)" }}>{a.title}</div>
                    <div style={{ fontSize: 13, color: "var(--sub)", marginTop: 3, lineHeight: 1.5 }}>{a.detail}</div>
                  </div>
                </div>
              ))}
            </div>}

            <PageFooter report={report} section="EXECUTIVE SUMMARY" />
          </div>
        </section>

        {/* ===== PAGE 2 · INSIGHT DASHBOARD ===== */}
        <section className="print-page">
          <div className="page-content">
            <PageHeader report={report} />
            <div style={{ marginTop: 34 }}>
              <SectionTitle mb={22}>ANALYSIS FACTS</SectionTitle>

              <div style={{ display: "grid", gridTemplateColumns: "repeat(5,1fr)", border: "1px solid var(--line2)", borderRadius: 9, overflow: "hidden", marginBottom: 22 }}>
                {metricCards.map((m) => (
                  <div key={m.k} style={{ padding: "14px 14px", borderRight: "1px solid var(--line)" }}>
                    <div style={metaLabel}>{m.k}</div>
                    <div style={{ fontSize: 20, fontWeight: 700, marginTop: 6, letterSpacing: "-.02em", color: m.accent ? "var(--accent)" : "var(--ink)" }}>{m.v}</div>
                  </div>
                ))}
              </div>

              <div style={{ display: "grid", gridTemplateColumns: totalRisks > 0 ? "1fr 1fr" : "1fr", gap: 18 }}>
                <InsightCard title="Configured persona context">
                  <p style={{ fontSize: 12, color: "var(--sub)", lineHeight: 1.5, margin: "0 0 8px" }}>User-selected configuration, not an evidence-derived finding.</p>
                  <p style={{ fontSize: 13, color: "var(--ink2)", lineHeight: 1.6, margin: 0 }}>{report.personaBrief.description}</p>
                </InsightCard>

                {totalRisks > 0 && <InsightCard title="Risk Severity Breakdown">
                  <div style={{ height: 14, borderRadius: 4, overflow: "hidden", display: "flex" }}>
                    <div style={{ width: `${(counts.High / totalRisks) * 100}%`, background: SEV_COLORS.High }} />
                    <div style={{ width: `${(counts.Medium / totalRisks) * 100}%`, background: SEV_COLORS.Medium }} />
                    <div style={{ width: `${(counts.Low / totalRisks) * 100}%`, background: SEV_COLORS.Low }} />
                  </div>
                  <div style={{ display: "flex", gap: 20, marginTop: 18 }}>
                    {([["High", counts.High, SEV_COLORS.High], ["Medium", counts.Medium, SEV_COLORS.Medium], ["Low", counts.Low, SEV_COLORS.Low]] as const).map(([label, count, color]) => (
                      <div key={label} style={{ display: "flex", alignItems: "center", gap: 7 }}>
                        <span style={{ width: 9, height: 9, borderRadius: 2, background: color }} />
                        <span style={{ fontSize: 12, color: "var(--ink)" }}>{label}</span>
                        <span style={{ fontFamily: mono, fontSize: 12, fontWeight: 600, color: "var(--sub)" }}>{count}</span>
                      </div>
                    ))}
                  </div>
                  <div style={{ fontSize: 11.5, color: "var(--sub)", marginTop: "auto", paddingTop: 16, lineHeight: 1.5 }}>
                    {totalRisks} persisted risks in this report.
                  </div>
                </InsightCard>}
              </div>
            </div>
            <PageFooter report={report} section="ANALYSIS FACTS" />
          </div>
        </section>

        {/* ===== PAGE 3 · RECOMMENDED WORKFLOW ===== */}
        {report.workflowSteps.length > 0 && (
        <section className="print-page print-flow">
          <div className="page-content">
            <PageHeader report={report} />
            <div style={{ marginTop: 34 }}>
              <SectionTitle mb={6}>RECOMMENDED WORKFLOW</SectionTitle>
              <div style={{ fontSize: 13.5, color: "var(--sub)", margin: "14px 0 4px", lineHeight: 1.5 }}>
                A sequenced, evidence-backed plan for the {report.persona} in the {report.market} market.
              </div>
              {report.workflowSteps.map((s, i) => (
                <div key={s.step} className="avoid-break" style={{ display: "flex", gap: 20, padding: "20px 0", borderBottom: i < report.workflowSteps.length - 1 ? "1px solid var(--line)" : "none" }}>
                  <div style={{ width: 34, height: 34, flex: "none", borderRadius: "50%", border: "1.5px solid #0a0a0b", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: mono, fontSize: 12, fontWeight: 600 }}>
                    {String(s.step).padStart(2, "0")}
                  </div>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 16, fontWeight: 600, letterSpacing: "-.01em", color: "var(--ink)" }}>{s.title}</div>
                    <div style={{ display: "flex", gap: 28, marginTop: 12, alignItems: "flex-start" }}>
                      <div style={{ flex: 1 }}>
                        <div style={fieldLabel}>WHY IT MATTERS</div>
                        <div style={{ fontSize: 13, color: "var(--ink2)", marginTop: 5, lineHeight: 1.55 }}>{s.whyItMatters}</div>
                        <div style={{ ...fieldLabel, marginTop: 12 }}>EXPECTED OUTPUT</div>
                        <div style={{ fontSize: 13, color: "var(--ink2)", marginTop: 5, lineHeight: 1.55 }}>{s.expectedOutput}</div>
                      </div>
                      <div style={{ flex: "none", textAlign: "right" }}>
                        <div style={fieldLabel}>EVIDENCE</div>
                        <div style={{ marginTop: 7 }}>
                          <EvidenceTag code={s.evidenceCode} />
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
            <PageFooter report={report} section="RECOMMENDED WORKFLOW" />
          </div>
        </section>
        )}

        {/* ===== PAGE 4 · RISK REGISTER & EVIDENCE ===== */}
        {report.risks.length > 0 && (
        <section className="print-page print-flow">
          <div className="page-content">
            <PageHeader report={report} />
            <div style={{ marginTop: 34 }}>
              <SectionTitle mb={0}>RISK REGISTER &amp; EVIDENCE</SectionTitle>
              <div style={{ display: "grid", gridTemplateColumns: RISK_COLS, gap: 14, padding: "14px 0 10px", borderBottom: "1.5px solid #0a0a0b", fontFamily: mono, fontSize: 9, color: "var(--sub)", letterSpacing: ".08em" }}>
                <span>SEVERITY</span>
                <span>RISK</span>
                <span>BUSINESS IMPACT</span>
                <span>EVIDENCE</span>
                <span>RECOMMENDED FIX</span>
                <span>OWNER</span>
              </div>
              {report.risks.map((r) => (
                <div key={r.title} className="avoid-break" style={{ display: "grid", gridTemplateColumns: RISK_COLS, gap: 14, padding: "16px 0", borderBottom: "1px solid var(--line)", alignItems: "start" }}>
                  <SevBadge sev={r.severity} />
                  <span style={{ fontSize: 12, fontWeight: 600, color: "var(--ink)", lineHeight: 1.4 }}>{r.title}</span>
                  <span style={{ fontSize: 11.5, color: "var(--ink2)", lineHeight: 1.5 }}>{r.businessImpact}</span>
                  {isInsufficient(r.evidenceCode) ? (
                    <span style={{ fontFamily: mono, fontSize: 9, fontWeight: 600, color: "var(--sub)", lineHeight: 1.4 }}>INSUFFICIENT<br />EVIDENCE</span>
                  ) : (
                    <span style={{ fontFamily: mono, fontSize: 10, fontWeight: 600, color: "var(--accent)", lineHeight: 1.4 }}>{r.evidenceCode}</span>
                  )}
                  <span style={{ fontSize: 11.5, color: "var(--ink2)", lineHeight: 1.5 }}>{r.recommendedFix}</span>
                  <span style={{ fontSize: 11.5, color: "var(--ink2)", lineHeight: 1.5 }}>{r.owner}</span>
                </div>
              ))}
              <div style={{ display: "flex", gap: 22, marginTop: 22, fontFamily: mono, fontSize: 10, color: "var(--sub)", letterSpacing: ".05em" }}>
                {([["HIGH", SEV_COLORS.High], ["MEDIUM", SEV_COLORS.Medium], ["LOW", SEV_COLORS.Low]] as const).map(([label, color]) => (
                  <div key={label} style={{ display: "flex", alignItems: "center", gap: 7 }}>
                    <span style={{ width: 10, height: 10, borderRadius: 2, background: color }} />
                    {label}
                  </div>
                ))}
              </div>
            </div>
            <PageFooter report={report} section="RISK REGISTER" />
          </div>
        </section>
        )}

        {/* ===== PAGE 5 · SOURCE APPENDIX ===== */}
        <section className="print-page print-flow">
          <div className="page-content">
            <PageHeader report={report} />
            <div style={{ marginTop: 34 }}>
              <SectionTitle mb={6}>SOURCE APPENDIX</SectionTitle>
              <div style={{ fontSize: 13.5, color: "var(--sub)", margin: "14px 0 4px", lineHeight: 1.5 }}>
                Every claim in this playbook is traceable to a source span in the analyzed corpus.
              </div>
              {report.citations.map((c, i) => {
                const binding = sourceAudit?.evidenceBindings.find((item) => item.citationId === c.id);
                return (
                  <div key={c.id + i} className="avoid-break" style={{ display: "flex", gap: 14, padding: "14px 0", borderBottom: i < report.citations.length - 1 ? "1px solid var(--line)" : "none", overflowWrap: "anywhere" }}>
                    <span style={{ fontFamily: mono, fontSize: 10, fontWeight: 600, color: "#fff", background: "#0a0a0b", padding: "3px 7px", borderRadius: 5, flex: "none", alignSelf: "flex-start", whiteSpace: "nowrap" }}>{binding?.citationId || c.id}</span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 13, fontWeight: 600, color: "var(--ink)" }}>{binding?.documentTitle || binding?.originalFilename || c.source}</div>
                      {binding && <div style={{ ...fieldLabel, marginTop: 4 }}>VERSION {binding.documentVersionId} · {(binding.headingPath.join(" / ") || binding.sectionTitle)}</div>}
                      <div style={{ fontSize: 12.5, color: "var(--ink2)", marginTop: 4, lineHeight: 1.55, fontStyle: "italic", whiteSpace: "pre-wrap" }}>&ldquo;{binding?.excerpt ?? (allowReportCitationFallback ? c.excerpt : "Frozen source binding unavailable for this citation.")}&rdquo;</div>
                      <div style={{ ...fieldLabel, marginTop: 8 }}>WHY THIS CITATION MATTERS</div>
                      <div style={{ fontSize: 12, color: "var(--sub)", marginTop: 4, lineHeight: 1.5 }}>{c.whyItMatters}</div>
                    </div>
                  </div>
                );
              })}
            </div>
            <PageFooter report={report} section="SOURCE APPENDIX" />
          </div>
        </section>

        {/* ===== PAGE 6 · PERSISTED ACTION CHECKLIST ===== */}
        {(report.suggestedActions.length > 0 || report.workflowSteps.length > 0) && (
        <section className="print-page print-flow">
          <div className="page-content">
            <PageHeader report={report} />
            <div style={{ marginTop: 34 }}>
              <SectionTitle mb={6}>PERSISTED ACTION CHECKLIST</SectionTitle>
              <div style={{ fontSize: 13.5, color: "var(--sub)", margin: "14px 0 22px", lineHeight: 1.5 }}>
                Only actions and workflow outputs recorded in the persisted report are included below.
              </div>

              {report.suggestedActions.length > 0 && (
                <ChecklistBlock title="RECORDED ACTIONS" items={report.suggestedActions.map((a) => a.title)} />
              )}

              {report.workflowSteps.length > 0 && <div style={{ marginTop: 24 }}>
                <div style={fieldLabel}>CHECKLIST ITEMS</div>
                <div style={{ marginTop: 12 }}>
                  {report.workflowSteps.map((s) => (
                    <div key={s.step} className="avoid-break" style={{ display: "flex", gap: 12, alignItems: "flex-start", padding: "11px 0", borderBottom: "1px solid var(--line)" }}>
                      <span style={{ width: 16, height: 16, flex: "none", border: "1.5px solid #0a0a0b", borderRadius: 4, marginTop: 1 }} />
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: 13.5, fontWeight: 600, color: "var(--ink)" }}>{s.title}</div>
                        <div style={{ fontSize: 12, color: "var(--sub)", marginTop: 2, lineHeight: 1.45 }}>{s.expectedOutput}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>}
            </div>
            <PageFooter report={report} section="PERSISTED ACTION CHECKLIST" />
          </div>
        </section>
        )}
        </>}
      </div>
    </div>
  );
}

/* ---------------- helpers ---------------- */

function ZeroClaimPrint({
  report,
  sourceAudit,
  counts,
}: {
  report: EvidentiaReport;
  sourceAudit: ReportSourceAudit | null;
  counts: { accepted: number; rejected: number; insufficient: number };
}) {
  const mode = report.generationMode ?? "deterministic";
  return (
    <>
      <section className="print-page print-flow">
        <div className="page-content">
          <PageHeader report={report} confidential showMeta={false} />
          <div style={{ marginTop: 38 }}>
            <div style={{ fontFamily: mono, fontSize: 11, color: "var(--accent)", letterSpacing: ".16em", textTransform: "uppercase" }}>Evidence analysis report</div>
            <h1 style={{ fontSize: 42, fontWeight: 700, letterSpacing: "-.03em", lineHeight: 1.05, margin: "12px 0 0" }}>{report.persona}</h1>
            <div style={{ fontSize: 15, color: "var(--sub)", marginTop: 10 }}>{report.company} — {report.market} market</div>
            <div style={{ fontFamily: mono, fontSize: 10, color: "var(--sub)", letterSpacing: ".08em", marginTop: 8 }}>
              GENERATION · {mode.toUpperCase()} · {formatStamp(report.generatedAt)} · TENANT CORPUS
            </div>
          </div>

          <div style={{ marginTop: 30, padding: "22px 24px", border: "1px solid var(--line2)", borderRadius: 9, background: "var(--accent-weak)" }}>
            <div style={{ ...fieldLabel, color: "var(--accent)" }}>EXECUTIVE STATUS</div>
            <h2 style={{ fontSize: 23, margin: "8px 0", lineHeight: 1.25 }}>No claims were sufficiently supported</h2>
            <p style={{ fontSize: 14, lineHeight: 1.65, color: "var(--ink2)", margin: 0 }}>{report.summary}</p>
            <p style={{ fontSize: 12.5, lineHeight: 1.6, color: "var(--sub)", margin: "9px 0 0" }}>
              The pipeline completed successfully and analyzed the frozen evidence. No candidate passed the deterministic support gate; rejected and insufficient candidates remain audit-only.
            </p>
          </div>

          <div style={{ marginTop: 26 }}>
            <SectionTitle>ANALYSIS FACTS</SectionTitle>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", border: "1px solid var(--line2)", borderRadius: 9, overflow: "hidden" }}>
              <MetaCell label="FROZEN VERSIONS" value={String(sourceAudit?.sourceVersionCount ?? 0)} />
              <MetaCell label="SELECTED EVIDENCE SECTIONS" value={String(sourceAudit?.evidenceSectionCount ?? 0)} />
              <MetaCell label="SOURCE BINDINGS" value={String(sourceAudit?.evidenceBindings.length ?? 0)} />
              <MetaCell label="ACCEPTED CLAIMS" value="0" />
              <MetaCell label="REJECTED CANDIDATES" value={String(counts.rejected)} />
              <MetaCell label="INSUFFICIENT CANDIDATES" value={String(counts.insufficient)} />
            </div>
          </div>

          <div style={{ marginTop: 26 }}>
            <SectionTitle>CONFIGURED PERSONA CONTEXT</SectionTitle>
            <p style={{ fontSize: 12.5, color: "var(--sub)", lineHeight: 1.55, margin: "0 0 9px" }}>
              User-selected configuration used to scope the analysis; this is not an evidence-derived finding.
            </p>
            <p style={{ fontSize: 14, color: "var(--ink2)", lineHeight: 1.65, margin: 0 }}>{report.personaBrief.description}</p>
          </div>
          <PageFooter report={report} section="EXECUTIVE STATUS" />
        </div>
      </section>

      <section className="print-page print-flow">
        <div className="page-content">
          <PageHeader report={report} />
          <div style={{ marginTop: 30 }}>
            <SectionTitle>SOURCE APPENDIX</SectionTitle>
            <p style={{ fontSize: 12.5, color: "var(--sub)", lineHeight: 1.55, margin: "0 0 10px" }}>
              Frozen report-local evidence reviewed during generation. These excerpts are provenance records, not accepted analytical claims.
            </p>
            {(sourceAudit?.evidenceBindings ?? []).map((binding, index) => (
              <div key={`${binding.citationId}-${binding.anchorId}-${index}`} className="avoid-break" style={{ padding: "14px 0", borderBottom: "1px solid var(--line)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                  <strong style={{ fontSize: 13 }}>{binding.citationId}</strong>
                  <span style={fieldLabel}>VERSION {binding.documentVersionId} · SECTION {binding.sectionOrdinal + 1}</span>
                </div>
                <div style={{ fontSize: 13, fontWeight: 600, marginTop: 5 }}>{binding.documentTitle || binding.originalFilename}</div>
                <div style={{ ...fieldLabel, marginTop: 4 }}>{binding.headingPath.join(" / ") || binding.sectionTitle}</div>
                <div style={{ fontSize: 12.5, color: "var(--ink2)", lineHeight: 1.6, fontStyle: "italic", whiteSpace: "pre-wrap", overflowWrap: "anywhere", marginTop: 7 }}>&ldquo;{binding.excerpt}&rdquo;</div>
              </div>
            ))}
          </div>

          {sourceAudit?.corpusMode === "tenant" && (
            <div style={{ marginTop: 28 }}>
              <SectionTitle>SOURCE AUDIT &amp; PROVENANCE</SectionTitle>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, fontFamily: mono, fontSize: 10, color: "var(--sub)", lineHeight: 1.5 }}>
                <div>CORPUS {sourceAudit.corpusMode.toUpperCase()}</div>
                <div>STATUS {sourceAudit.generationStatus.toUpperCase()}</div>
                <div>RETRIEVAL {sourceAudit.retrievalEngineVersion ?? "—"}</div>
                <div>GENERATION {sourceAudit.executionMode ?? "—"}</div>
                <div>{sourceAudit.sourceVersionCount} FROZEN VERSION{sourceAudit.sourceVersionCount === 1 ? "" : "S"}</div>
                <div>{sourceAudit.evidenceSectionCount} SELECTED EVIDENCE SECTIONS</div>
              </div>
              {sourceAudit.corpusSnapshotDigest && (
                <div style={{ ...fieldLabel, overflowWrap: "anywhere", marginTop: 10 }}>SNAPSHOT {sourceAudit.corpusSnapshotDigest}</div>
              )}
            </div>
          )}
          <PageFooter report={report} section="SOURCE APPENDIX" />
        </div>
      </section>
    </>
  );
}

const RISK_COLS = "64px 1.1fr 1.3fr 62px 1.3fr 72px";

const metaLabel: React.CSSProperties = { fontFamily: mono, fontSize: 9, color: "var(--sub)", letterSpacing: ".08em" };
const fieldLabel: React.CSSProperties = { fontFamily: mono, fontSize: 9.5, color: "var(--sub)", letterSpacing: ".08em" };

function PageHeader({ report, confidential = false, showMeta = true }: { report: EvidentiaReport; confidential?: boolean; showMeta?: boolean }) {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", paddingBottom: 16, borderBottom: "1px solid var(--line)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <Logo size={24} showWordmark />
        <span style={{ fontFamily: mono, fontSize: 9.5, color: "var(--sub)", letterSpacing: ".12em" }}>PERSONA PLAYBOOK</span>
      </div>
      {confidential ? (
        <span style={{ fontFamily: mono, fontSize: 9.5, color: "var(--sub)", letterSpacing: ".1em" }}>CONFIDENTIAL</span>
      ) : showMeta ? (
        <span style={{ fontFamily: mono, fontSize: 9.5, color: "var(--sub)", letterSpacing: ".1em" }}>
          {report.persona} · {report.market}
        </span>
      ) : null}
    </div>
  );
}

function PageFooter({ report, section }: { report: EvidentiaReport; section: string }) {
  return (
    <div style={{ marginTop: "auto", paddingTop: 20, borderTop: "1px solid var(--line)", display: "flex", justifyContent: "space-between", gap: 12, fontFamily: mono, fontSize: 9, color: "var(--sub)", letterSpacing: ".08em" }}>
      <span>EVIDENTIA · {report.company} · {report.persona} · {report.market}</span>
      <span>{section} · CONFIDENTIAL</span>
    </div>
  );
}

function SectionTitle({ children, mb = 16 }: { children: React.ReactNode; mb?: number }) {
  return (
    <div style={{ fontFamily: mono, fontSize: 10.5, color: "#0a0a0b", letterSpacing: ".12em", fontWeight: 600, paddingBottom: 9, borderBottom: "1.5px solid #0a0a0b", marginBottom: mb }}>
      {children}
    </div>
  );
}

function MetaCell({ label, value, mono: isMono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div style={{ padding: "15px 16px", borderRight: "1px solid var(--line)" }}>
      <div style={metaLabel}>{label}</div>
      <div style={{ fontFamily: isMono ? mono : undefined, fontSize: isMono ? 11 : 13, fontWeight: isMono ? 500 : 600, marginTop: 6, lineHeight: 1.3 }}>{value}</div>
    </div>
  );
}

function EvidenceTag({ code }: { code: string }) {
  if (isInsufficient(code)) {
    return (
      <span
        title="No source section met the grounding threshold"
        style={{ display: "inline-block", fontFamily: mono, fontSize: 9, fontWeight: 600, letterSpacing: ".04em", color: "var(--sub)", background: "var(--shell)", border: "1px dashed var(--line2)", padding: "4px 7px", borderRadius: 5, whiteSpace: "nowrap" }}
      >
        INSUFFICIENT EVIDENCE
      </span>
    );
  }
  return (
    <span style={{ display: "inline-block", fontFamily: mono, fontSize: 10.5, fontWeight: 600, color: "#fff", background: "#0a0a0b", padding: "4px 8px", borderRadius: 5, whiteSpace: "nowrap" }}>
      {code}
    </span>
  );
}

function SevBadge({ sev }: { sev: RiskItem["severity"] }) {
  return (
    <span style={{ fontFamily: mono, fontSize: 9.5, fontWeight: 600, letterSpacing: ".06em", color: "#fff", background: SEV_COLORS[sev], padding: "4px 8px", borderRadius: 4, flex: "none", lineHeight: 1, whiteSpace: "nowrap", alignSelf: "flex-start" }}>
      {sev.toUpperCase()}
    </span>
  );
}

function InsightCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="avoid-break" style={{ display: "flex", flexDirection: "column", border: "1px solid var(--line2)", borderRadius: 10, padding: "20px 22px" }}>
      <div style={{ fontFamily: mono, fontSize: 10, color: "var(--sub)", letterSpacing: ".06em", textTransform: "uppercase", marginBottom: 18 }}>{title}</div>
      {children}
    </div>
  );
}

function ChecklistBlock({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <div style={fieldLabel}>{title}</div>
      <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 10 }}>
        {items.map((it) => (
          <div key={it} style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
            <span style={{ width: 14, height: 14, flex: "none", border: "1.5px solid #0a0a0b", borderRadius: 4, marginTop: 1 }} />
            <span style={{ fontSize: 12.5, color: "var(--ink2)", lineHeight: 1.4 }}>{it}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
