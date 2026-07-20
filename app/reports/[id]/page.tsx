"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import AppShell from "@/components/AppShell";
import DownloadDocxButton from "@/components/DownloadDocxButton";
import { useSession } from "@/components/SessionProvider";
import {
  fetchBackendReport,
  fetchReportFeedback,
  fetchReportClaimAudit,
  fetchReportSourceAudit,
  putCitationFeedback,
  putItemFeedback,
  putReportFeedback,
} from "@/lib/reportsApi";
import { claimDecisionCounts, hasEmptyAnalyticalProjection, hasZeroAcceptedAnalyticalOutput } from "@/lib/reportPresentation";
import type {
  Citation,
  CitationFeedbackVerdict,
  EvidentiaReport,
  ItemFeedbackVerdict,
  ReportFeedbackSnapshot,
  ReportFeedbackVerdict,
  ReportClaimAudit,
  ReportEvidenceSource,
  ReportSourceAudit,
} from "@/lib/types";

const mono = "var(--font-plex-mono), monospace";

const SEV_COLORS: Record<"High" | "Medium" | "Low", string> = {
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

export default function ReportDetailPage() {
  const router = useRouter();
  const { user, activeCompany, status: sessionStatus } = useSession();
  const params = useParams<{ id: string }>();
  const id = (Array.isArray(params.id) ? params.id[0] : params.id) || "current";
  const sessionScope = `${user?.id ?? "anonymous"}:${activeCompany?.id ?? "none"}`;
  const scopeRef = useRef(sessionScope);

  const [report, setReport] = useState<EvidentiaReport | null>(null);
  const [sourceAudit, setSourceAudit] = useState<ReportSourceAudit | null>(null);
  const [claimAudit, setClaimAudit] = useState<ReportClaimAudit | null>(null);
  const [feedback, setFeedback] = useState<ReportFeedbackSnapshot | null>(null);
  const [reportVerdict, setReportVerdict] = useState<ReportFeedbackVerdict | "">("");
  const [privateText, setPrivateText] = useState("");
  const [feedbackStatus, setFeedbackStatus] = useState("");
  const [savingFeedback, setSavingFeedback] = useState<string | null>(null);
  const [loadedScope, setLoadedScope] = useState<string | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "missing">("loading");

  useEffect(() => {
    scopeRef.current = sessionScope;
  }, [sessionScope]);

  useEffect(() => {
    let cancelled = false;
    if (sessionStatus !== "authenticated") return;
    // The backend is the only source of truth. A 404 means the report does not
    // exist *for this tenant* — we must NOT fall back to a locally cached or
    // locally generated report, which is how another account's data (or a fake
    // report) could be rendered as if it were real.
    (async () => {
      const [backendReport, audit, claims, currentFeedback] = await Promise.all([
        fetchBackendReport(id),
        fetchReportSourceAudit(id),
        fetchReportClaimAudit(id),
        fetchReportFeedback(id),
      ]);
      if (cancelled) return;
      if (backendReport) {
        setReport(backendReport);
        setSourceAudit(audit);
        setClaimAudit(claims);
        setFeedback(currentFeedback);
        setReportVerdict(currentFeedback?.report?.verdict ?? "");
        setPrivateText(currentFeedback?.report?.privateText ?? "");
        setLoadedScope(sessionScope);
        setState("ready");
      } else {
        setReport(null);
        setSourceAudit(null);
        setClaimAudit(null);
        setFeedback(null);
        setReportVerdict("");
        setPrivateText("");
        setFeedbackStatus("");
        setSavingFeedback(null);
        setLoadedScope(sessionScope);
        setState("missing");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id, sessionScope, sessionStatus]);

  const reloadFeedback = async (startedScope: string) => {
    const current = await fetchReportFeedback(id);
    if (scopeRef.current === startedScope) setFeedback(current);
  };

  const saveReportVerdict = async () => {
    if (!reportVerdict) return;
    const startedScope = sessionScope;
    setSavingFeedback("report");
    setFeedbackStatus("");
    const ok = await putReportFeedback(id, reportVerdict, privateText);
    if (scopeRef.current !== startedScope) return;
    if (ok) await reloadFeedback(startedScope);
    setSavingFeedback(null);
    setFeedbackStatus(ok ? "Feedback saved privately to your organization." : "Feedback could not be saved.");
  };

  const saveItemVerdict = async (path: string, verdict: ItemFeedbackVerdict) => {
    const startedScope = sessionScope;
    setSavingFeedback(path);
    const ok = await putItemFeedback(id, path, "risk", verdict);
    if (scopeRef.current !== startedScope) return;
    if (ok) await reloadFeedback(startedScope);
    setSavingFeedback(null);
    setFeedbackStatus(ok ? "Item feedback saved." : "Item feedback could not be saved.");
  };

  const saveCitationVerdict = async (
    path: string,
    citationId: string,
    verdict: CitationFeedbackVerdict,
  ) => {
    const startedScope = sessionScope;
    setSavingFeedback(path);
    const ok = await putCitationFeedback(id, path, citationId, verdict);
    if (scopeRef.current !== startedScope) return;
    if (ok) await reloadFeedback(startedScope);
    setSavingFeedback(null);
    setFeedbackStatus(ok ? "Citation feedback saved." : "Citation feedback could not be saved.");
  };

  const loadingCurrentScope = sessionStatus === "loading" || loadedScope !== sessionScope;
  if (state !== "ready" || !report || loadingCurrentScope) {
    return (
      <AppShell active="reports">
        <div style={{ padding: 48, maxWidth: 560 }}>
          <h1 style={{ fontSize: 22, fontWeight: 700, letterSpacing: "-.02em", margin: 0 }}>
            {state === "loading" || loadingCurrentScope ? "Loading report…" : "Report not found"}
          </h1>
          {state === "missing" && !loadingCurrentScope && (
            <>
              <p style={{ fontSize: 13.5, color: "var(--sub)", marginTop: 10, lineHeight: 1.6 }}>
                This report doesn&apos;t exist, or it belongs to a different organization.
              </p>
              <button
                onClick={() => router.push("/reports")}
                style={{
                  marginTop: 18, fontFamily: "inherit", fontSize: 14, fontWeight: 600,
                  color: "#fff", background: "#0a0a0b", border: "none",
                  padding: "11px 18px", borderRadius: 9, cursor: "pointer",
                }}
              >
                Back to reports
              </button>
            </>
          )}
        </div>
      </AppShell>
    );
  }

  const { metrics, personaBrief } = report;
  const openPrint = () => window.open(`/playbook/${report.id}/print`, "_blank");

  const mode = report.generationMode ?? "deterministic";
  const isLlm = mode.startsWith("llm");
  const modeLabel =
    mode === "llm-summary" ? "LLM-SUMMARY" : mode === "llm-assisted" ? "LLM-ASSISTED" : "DETERMINISTIC";
  const zeroClaims = hasZeroAcceptedAnalyticalOutput(report, claimAudit);
  const emptyAnalyticalProjection = hasEmptyAnalyticalProjection(report);
  const decisionCounts = claimDecisionCounts(claimAudit);
  const bindingByCitation = new Map(
    (sourceAudit?.evidenceBindings ?? []).map((binding) => [binding.citationId, binding]),
  );

  const metricCards = zeroClaims ? [
    { k: "Frozen versions", v: String(sourceAudit?.sourceVersionCount ?? 0), s: "report-local corpus", accent: false },
    { k: "Evidence sections", v: String(sourceAudit?.evidenceSectionCount ?? 0), s: "selected for analysis", accent: false },
    { k: "Source bindings", v: String(sourceAudit?.evidenceBindings.length ?? 0), s: "frozen citations available", accent: false },
    { k: "Accepted claims", v: "0", s: "deterministic support gate", accent: false },
    { k: "Analytical confidence", v: "N/A", s: "No accepted claims to score", accent: false },
  ] : [
    {
      k: "Documents",
      v: String(metrics.documentsAnalyzed),
      s:
        sourceAudit?.corpusMode === "tenant"
          ? `${sourceAudit.sourceVersionCount} frozen versions`
          : "corpus unavailable",
      accent: false,
    },
    { k: "Citations", v: String(metrics.citationsUsed), s: "source-traced", accent: false },
    { k: "Risks flagged", v: String(metrics.risksFlagged), s: severityBreakdown(report), accent: false },
    emptyAnalyticalProjection
      ? { k: "Analytical confidence", v: "N/A", s: "No analytical output to score", accent: false }
      : { k: "Baseline score", v: `${report.confidence}%`, s: "document-count heuristic", accent: false },
  ];

  return (
    <AppShell active="reports" compactOnMobile>
      {/* header */}
      <div className="ev-report-header" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 28px", minHeight: 60, background: "var(--paper)", borderBottom: "1px solid var(--line)", position: "sticky", top: 0, zIndex: 5 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
          <button onClick={() => router.push("/reports")} style={{ background: "transparent", border: "none", cursor: "pointer", font: "inherit", fontWeight: 700, fontSize: 14.5, color: "var(--ink)" }}>Reports</button>
          <span style={{ color: "var(--line2)" }}>/</span>
          <span style={{ fontSize: 13.5, color: "var(--sub)" }}>{report.company} · {report.market}</span>
        </div>
        <div className="ev-report-actions" style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <button onClick={() => router.push("/workspace")} style={{ fontFamily: "inherit", fontSize: 13, fontWeight: 500, color: "var(--ink)", background: "var(--paper)", border: "1px solid var(--line2)", padding: "8px 15px", borderRadius: 8, cursor: "pointer" }}>
            New report
          </button>
          <DownloadDocxButton reportId={report.id} />
          <button onClick={openPrint} style={{ fontFamily: "inherit", fontSize: 13, fontWeight: 600, color: "#fff", background: "#0a0a0b", border: "none", padding: "9px 16px", borderRadius: 8, cursor: "pointer", display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ width: 6, height: 6, borderRadius: 1, background: "var(--accent)" }} />
            Export playbook (PDF)
          </button>
        </div>
      </div>

      <div className="ev-report-content" style={{ maxWidth: zeroClaims ? 1040 : 1240, width: "100%", margin: "0 auto", padding: "32px 40px 64px" }}>
        {/* title block */}
        <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", flexWrap: "wrap", gap: 16, marginBottom: 26 }}>
          <div>
            <div style={{ fontFamily: mono, fontSize: 11.5, color: "var(--accent)", letterSpacing: ".1em", textTransform: "uppercase" }}>
              Persona report · {report.market}
            </div>
            <h1 style={{ fontSize: 32, fontWeight: 700, letterSpacing: "-.02em", margin: "8px 0 0" }}>{report.persona}</h1>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
              <span
                style={{
                  fontFamily: mono,
                  fontSize: 10,
                  fontWeight: 600,
                  letterSpacing: ".06em",
                  padding: "4px 9px",
                  borderRadius: 5,
                  color: isLlm ? "#fff" : "var(--ink2)",
                  background: isLlm ? "var(--accent)" : "var(--shell)",
                  border: isLlm ? "none" : "1px solid var(--line2)",
                }}
                title={isLlm && report.llmModel ? `${report.llmProvider} · ${report.llmModel}` : undefined}
              >
                {modeLabel}
              </span>
              <span style={{ fontFamily: mono, fontSize: 10, fontWeight: 600, letterSpacing: ".06em", padding: "4px 9px", borderRadius: 5, color: "var(--ink2)", background: "var(--shell)", border: "1px solid var(--line2)" }}>
                {sourceAudit?.corpusMode === "tenant" ? "TENANT CORPUS" : "CORPUS UNAVAILABLE"}
              </span>
              {personaBrief.isCustom && (
                <span style={{ fontFamily: mono, fontSize: 10, fontWeight: 600, letterSpacing: ".06em", padding: "4px 9px", borderRadius: 5, color: "var(--ink2)", background: "var(--shell)", border: "1px solid var(--line2)" }}>
                  CUSTOM ROLE
                </span>
              )}
            </div>
          </div>
          <div style={{ fontFamily: mono, fontSize: 11.5, color: "var(--sub)", textAlign: "right", lineHeight: 1.7 }}>
            <div>GENERATED {formatStamp(report.generatedAt)}</div>
            <div>
              {zeroClaims
                ? `${sourceAudit?.sourceVersionCount ?? 0} FROZEN VERSION${sourceAudit?.sourceVersionCount === 1 ? "" : "S"} · ANALYSIS COMPLETED`
                : emptyAnalyticalProjection
                  ? `${metrics.documentsAnalyzed} DOCS · NO ANALYTICAL OUTPUT TO SCORE`
                  : `${metrics.documentsAnalyzed} DOCS · BASELINE SCORE ${report.confidence}%`}
            </div>
          </div>
        </div>

        {/* metric cards */}
        <div style={{ display: "grid", gridTemplateColumns: `repeat(${metricCards.length},1fr)`, gap: 1, background: "var(--line)", border: "1px solid var(--line)", borderRadius: 12, overflow: "hidden", marginBottom: 28 }} className="ev-metric-grid">
          {metricCards.map((m) => (
            <div key={m.k} style={{ padding: "20px 20px", background: "var(--panel)" }}>
              <div style={{ fontFamily: mono, fontSize: 10.5, color: "var(--sub)", letterSpacing: ".06em", textTransform: "uppercase" }}>{m.k}</div>
              <div style={{ fontSize: 27, fontWeight: 700, letterSpacing: "-.02em", marginTop: 9, color: m.accent ? "var(--accent)" : "var(--ink)" }}>{m.v}</div>
              <div style={{ fontSize: 11.5, color: "var(--sub)", marginTop: 4 }}>{m.s}</div>
            </div>
          ))}
        </div>

        {/* executive status / summary */}
        <div style={{ background: zeroClaims ? "var(--accent-weak)" : "var(--panel)", border: "1px solid var(--line)", borderRadius: 12, padding: "22px 26px", marginBottom: 28 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
            <span style={{ fontFamily: mono, fontSize: 11, color: zeroClaims ? "var(--accent)" : "var(--sub)", letterSpacing: ".08em" }}>
              {zeroClaims ? "NO SUPPORTED ANALYTICAL OUTPUT" : "EXECUTIVE SUMMARY"}
            </span>
            <span style={{ flex: 1, height: 1, background: "var(--line)" }} />
          </div>
          {zeroClaims && (
            <h2 style={{ fontSize: 21, lineHeight: 1.3, letterSpacing: "-.01em", margin: "0 0 8px" }}>
              No claims were sufficiently supported
            </h2>
          )}
          <p style={{ fontSize: 15, lineHeight: 1.62, color: "var(--ink2)", margin: 0 }}>{report.summary}</p>
          {zeroClaims && (
            <p style={{ fontSize: 13.5, lineHeight: 1.6, color: "var(--sub)", margin: "10px 0 0" }}>
              The pipeline completed successfully and analyzed the frozen evidence. No candidate passed the deterministic support gate; rejected and insufficient candidates remain audit-only ({decisionCounts.rejected} rejected, {decisionCounts.insufficient} insufficient).
            </p>
          )}
        </div>

        {/* analytical body; zero-claim reports deliberately collapse to one column */}
        <div style={{ display: "grid", gridTemplateColumns: zeroClaims ? "1fr" : "1fr 380px", gap: 28, alignItems: "start" }} className="ev-report-grid">
          {/* LEFT */}
          <div style={{ display: "flex", flexDirection: "column", gap: 28 }}>
            <Card>
              <SectionLabel>{zeroClaims ? "CONFIGURED PERSONA CONTEXT" : "PERSONA BRIEF"}</SectionLabel>
              {zeroClaims && (
                <p style={{ fontSize: 12.5, color: "var(--sub)", lineHeight: 1.55, margin: "0 0 12px" }}>
                  User-selected configuration used to scope the analysis; this is not an evidence-derived finding.
                </p>
              )}
              <p style={{ fontSize: 16, lineHeight: 1.62, color: "var(--ink2)", margin: 0 }}>{personaBrief.description}</p>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 20 }}>
                {personaBrief.priorities.map((p) => (
                  <span key={p} style={{ fontFamily: mono, fontSize: 11, color: "var(--ink)", background: "var(--shell)", border: "1px solid var(--line)", padding: "6px 11px", borderRadius: 6 }}>{p}</span>
                ))}
              </div>
            </Card>

            {report.workflowSteps.length > 0 && <Card>
              <SectionLabel>RECOMMENDED WORKFLOW</SectionLabel>
              <div style={{ display: "flex", flexDirection: "column" }}>
                {report.workflowSteps.map((s, i) => (
                  <div key={s.step} style={{ display: "flex", gap: 15, alignItems: "flex-start", padding: "15px 0", borderBottom: i < report.workflowSteps.length - 1 ? "1px solid var(--line)" : "none" }}>
                    <div style={{ width: 26, height: 26, flex: "none", borderRadius: "50%", border: "1px solid var(--line2)", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: mono, fontSize: 12, fontWeight: 600, color: "var(--ink)" }}>
                      {String(s.step).padStart(2, "0")}
                    </div>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 14.5, fontWeight: 600, color: "var(--ink)" }}>{s.title}</div>
                      <div style={{ fontSize: 13, color: "var(--sub)", marginTop: 3, lineHeight: 1.5 }}>{s.description}</div>
                    </div>
                    <EvidenceChip code={s.evidenceCode} />
                  </div>
                ))}
              </div>
            </Card>}

            {report.risks.length > 0 && <Card>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 18 }}>
                <span style={{ fontFamily: mono, fontSize: 11, color: "var(--sub)", letterSpacing: ".08em" }}>RISKS &amp; WARNINGS</span>
                <span style={{ fontFamily: mono, fontSize: 11, color: "var(--sub)" }}>{report.risks.length} flagged</span>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                {report.risks.map((r, riskIndex) => {
                    const color = SEV_COLORS[r.severity] ?? SEV_COLORS.Low;
                    const insufficient = isInsufficient(r.evidenceCode);
                    const itemPath = `/risks/${riskIndex}`;
                    const selected = feedback?.items.find((item) => item.itemPath === itemPath)?.verdict;
                    return (
                      <div key={r.title} style={{ display: "flex", gap: 14, padding: "15px 16px", border: "1px solid var(--line)", borderRadius: 10, background: "var(--shell)", borderLeft: `3px solid ${color}` }}>
                        <span style={{ fontFamily: mono, fontSize: 10, fontWeight: 600, letterSpacing: ".05em", padding: "4px 8px", borderRadius: 5, height: "fit-content", flex: "none", color: "#fff", background: color }}>
                          {r.severity.toUpperCase()}
                        </span>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontSize: 14, fontWeight: 600, color: "var(--ink)" }}>{r.title}</div>
                          <div style={{ fontSize: 13, color: "var(--ink2)", marginTop: 4, lineHeight: 1.5 }}>{r.description}</div>
                          <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
                            <EvidenceChip code={r.evidenceCode} small />
                            <span style={{ fontFamily: mono, fontSize: 11, color: "var(--sub)" }}>{insufficient ? "documentation gap" : r.owner}</span>
                          </div>
                          <FeedbackChoices
                            label={`Risk ${riskIndex + 1} feedback`}
                            choices={[
                              ["accepted", "Accept"],
                              ["rejected", "Reject"],
                              ["insufficient_evidence", "Insufficient"],
                            ]}
                            selected={selected}
                            disabled={savingFeedback === itemPath}
                            onChoose={(value) => void saveItemVerdict(itemPath, value as ItemFeedbackVerdict)}
                          />
                        </div>
                      </div>
                    );
                })}
              </div>
            </Card>}
          </div>

          {/* RIGHT */}
          <div style={{ display: "flex", flexDirection: "column", gap: 28 }}>
            <Card pad="24px 24px">
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
                <span style={{ fontFamily: mono, fontSize: 11, color: "var(--sub)", letterSpacing: ".08em" }}>CITATIONS</span>
                <span style={{ fontFamily: mono, fontSize: 11, color: "var(--sub)" }}>{report.citations.length} sources</span>
              </div>
              {report.citations.length === 0 ? (
                <EmptyRow text="No source citations were bound for this report." />
              ) : (
                <div className={zeroClaims ? "ev-citation-grid" : undefined} style={{ display: "grid", gridTemplateColumns: zeroClaims ? "repeat(2, minmax(0, 1fr))" : "1fr", gap: zeroClaims ? 14 : 0 }}>
                  {report.citations.map((c, i) => (
                    <CitationCard
                      key={c.id + i}
                      citation={c}
                      binding={bindingByCitation.get(c.id)}
                      allowReportFallback={sourceAudit?.corpusMode === "demo"}
                      bordered={zeroClaims || i < report.citations.length - 1}
                      selected={feedback?.citations.find((item) => item.itemPath === `/citations/${i}` && item.citationId === c.id)?.verdict}
                      disabled={savingFeedback === `/citations/${i}`}
                      onChoose={(value) => void saveCitationVerdict(`/citations/${i}`, c.id, value)}
                    />
                  ))}
                </div>
              )}
            </Card>

            {sourceAudit?.corpusMode === "tenant" && (
              <Card pad="24px 24px">
                <SectionLabel>SOURCE AUDIT</SectionLabel>
                <div style={{ display: "grid", gap: 8, fontFamily: mono, fontSize: 10.5, color: "var(--sub)", lineHeight: 1.5 }}>
                  <div>CORPUS {sourceAudit.corpusMode.toUpperCase()}</div>
                  <div>{sourceAudit.sourceVersionCount} VERSION{sourceAudit.sourceVersionCount === 1 ? "" : "S"} · {sourceAudit.evidenceSectionCount} SELECTED SECTIONS</div>
                  <div>RETRIEVAL {sourceAudit.retrievalEngineVersion ?? "—"}</div>
                  <div>GENERATION {sourceAudit.executionMode ?? "—"}</div>
                  {sourceAudit.corpusSnapshotDigest && (
                    <div title={sourceAudit.corpusSnapshotDigest}>SNAPSHOT {sourceAudit.corpusSnapshotDigest.slice(0, 24)}…</div>
                  )}
                </div>
              </Card>
            )}

            {!zeroClaims && report.suggestedActions.length > 0 && <div style={{ background: "#0a0a0b", color: "#f5f5f3", borderRadius: 12, padding: "24px 24px" }}>
              <div style={{ fontFamily: mono, fontSize: 11, color: "rgba(245,245,243,.5)", letterSpacing: ".08em", marginBottom: 18 }}>SUGGESTED ACTIONS</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 11 }}>
                {report.suggestedActions.map((a) => (
                  <div key={a.title} style={{ display: "flex", gap: 13, alignItems: "flex-start", padding: "13px 14px", border: "1px solid rgba(255,255,255,.12)", borderRadius: 9 }}>
                    <span style={{ color: "var(--accent)", fontFamily: mono, fontSize: 13, fontWeight: 600, lineHeight: 1.3 }}>→</span>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 14, fontWeight: 600 }}>{a.title}</div>
                      <div style={{ fontSize: 12.5, color: "rgba(245,245,243,.55)", marginTop: 3, lineHeight: 1.45 }}>{a.detail}</div>
                    </div>
                  </div>
                ))}
              </div>
              <button onClick={openPrint} style={{ width: "100%", marginTop: 18, fontFamily: "inherit", fontSize: 13.5, fontWeight: 600, color: "#0a0a0b", background: "#fff", border: "none", padding: 12, borderRadius: 9, cursor: "pointer" }}>
                Export full playbook →
              </button>
            </div>}
          </div>
        </div>

        <Card>
          <SectionLabel>REPORT FEEDBACK</SectionLabel>
          <p style={{ fontSize: 13, color: "var(--sub)", lineHeight: 1.5, margin: "0 0 14px" }}>
            Feedback is private to your organization and does not automatically change claim patterns or thresholds.
          </p>
          <FeedbackChoices
            label="Overall report feedback"
            choices={[["correct_useful", "Correct & useful"], ["partially_correct", "Partially correct"], ["incorrect", "Incorrect"]]}
            selected={reportVerdict || undefined}
            disabled={savingFeedback === "report"}
            onChoose={(value) => setReportVerdict(value as ReportFeedbackVerdict)}
          />
          <label style={{ display: "block", fontSize: 12.5, color: "var(--ink2)", marginTop: 14 }}>
            Private note (optional)
            <textarea
              aria-label="Private feedback note"
              value={privateText}
              maxLength={2000}
              onChange={(event) => setPrivateText(event.target.value)}
              style={{ display: "block", width: "100%", minHeight: 74, resize: "vertical", marginTop: 7, border: "1px solid var(--line2)", borderRadius: 8, padding: 10, font: "inherit", fontSize: 13, background: "var(--paper)", color: "var(--ink)" }}
            />
          </label>
          <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 12 }}>
            <button
              type="button"
              disabled={!reportVerdict || savingFeedback === "report"}
              onClick={() => void saveReportVerdict()}
              style={{ border: 0, borderRadius: 7, padding: "8px 13px", background: "#0a0a0b", color: "#fff", font: "inherit", fontSize: 12.5, fontWeight: 600, cursor: "pointer", opacity: !reportVerdict || savingFeedback === "report" ? .55 : 1 }}
            >
              {savingFeedback === "report" ? "Saving…" : "Save feedback"}
            </button>
            <span role="status" style={{ fontSize: 12, color: "var(--sub)" }}>{feedbackStatus}</span>
          </div>
        </Card>
      </div>

      <style jsx global>{`
        @media (max-width: 1040px) {
          .ev-report-grid {
            grid-template-columns: 1fr !important;
          }
        }
        @media (max-width: 820px) {
          .ev-citation-grid {
            grid-template-columns: 1fr !important;
          }
        }
        @media (max-width: 760px) {
          .ev-app-shell-compact-mobile > aside {
            display: none !important;
          }
          .ev-metric-grid {
            grid-template-columns: repeat(2, 1fr) !important;
          }
          .ev-metric-grid > :last-child:nth-child(odd) {
            grid-column: 1 / -1;
          }
          .ev-report-header {
            position: static !important;
            align-items: flex-start !important;
            gap: 12px;
            padding: 12px 16px !important;
            flex-direction: column;
          }
          .ev-report-actions {
            width: 100%;
          }
          .ev-report-content {
            padding: 24px 16px 48px !important;
          }
        }
      `}</style>
    </AppShell>
  );
}

function severityBreakdown(report: EvidentiaReport): string {
  const h = report.risks.filter((r) => r.severity === "High").length;
  const m = report.risks.filter((r) => r.severity === "Medium").length;
  const l = report.risks.filter((r) => r.severity === "Low").length;
  return `${h} high · ${m} med · ${l} low`;
}

function CitationCard({
  citation,
  binding,
  allowReportFallback,
  bordered,
  selected,
  disabled,
  onChoose,
}: {
  citation: Citation;
  binding?: ReportEvidenceSource;
  allowReportFallback: boolean;
  bordered: boolean;
  selected?: string;
  disabled?: boolean;
  onChoose: (value: CitationFeedbackVerdict) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const excerpt = binding?.excerpt ?? (allowReportFallback ? citation.excerpt : "Frozen source binding unavailable for this citation.");
  const previewLimit = 320;
  const hasMore = excerpt.length > previewLimit;
  const shownExcerpt = hasMore && !expanded ? `${excerpt.slice(0, previewLimit).trimEnd()}…` : excerpt;
  const title = binding?.documentTitle || binding?.originalFilename || citation.source;
  const sectionPath = binding?.headingPath.length
    ? binding.headingPath.join(" / ")
    : binding?.sectionTitle || citation.section;

  return (
    <div style={{ display: "flex", gap: 12, minWidth: 0, padding: 13, border: bordered ? "1px solid var(--line)" : "none", borderRadius: bordered ? 9 : 0, overflowWrap: "anywhere" }}>
      <span style={{ fontFamily: mono, fontSize: 10.5, fontWeight: 600, color: "#fff", background: "#0a0a0b", padding: "3px 7px", borderRadius: 5, flex: "none", alignSelf: "flex-start", whiteSpace: "nowrap" }}>{binding?.citationId || citation.id}</span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12.5, fontWeight: 600, color: "var(--ink)" }}>{title}</div>
        {sectionPath && (
          <div style={{ fontFamily: mono, fontSize: 10.5, color: "var(--sub)", marginTop: 2 }}>{sectionPath}</div>
        )}
        {binding && (
          <div style={{ fontFamily: mono, fontSize: 10, color: "var(--sub)", marginTop: 3 }}>
            VERSION {binding.documentVersionId} · SECTION {binding.sectionOrdinal + 1}
          </div>
        )}
        <div style={{ fontSize: 12.5, color: "var(--ink2)", marginTop: 6, lineHeight: 1.55, fontStyle: "italic", whiteSpace: "pre-wrap" }}>&ldquo;{shownExcerpt}&rdquo;</div>
        {hasMore && (
          <button
            type="button"
            aria-expanded={expanded}
            onClick={() => setExpanded((value) => !value)}
            style={{ border: 0, padding: 0, marginTop: 7, background: "transparent", color: "var(--accent)", font: "inherit", fontSize: 11.5, fontWeight: 600, cursor: "pointer" }}
          >
            {expanded ? "Show less" : "Show more"}
          </button>
        )}
        <FeedbackChoices
          label={`Citation ${citation.id} feedback`}
          choices={[["correct", "Correct"], ["irrelevant", "Irrelevant"]]}
          selected={selected}
          disabled={disabled}
          onChoose={(value) => onChoose(value as CitationFeedbackVerdict)}
        />
      </div>
    </div>
  );
}

function EvidenceChip({ code, small }: { code: string; small?: boolean }) {
  if (isInsufficient(code)) {
    return (
      <span
        title="No source section met the grounding threshold — this item is marked insufficient evidence rather than citing an unrelated source."
        style={{ fontFamily: mono, fontSize: small ? 9.5 : 10, fontWeight: 600, letterSpacing: ".04em", color: "var(--sub)", background: "var(--shell)", border: "1px dashed var(--line2)", padding: "3px 7px", borderRadius: 5, whiteSpace: "nowrap", alignSelf: "center" }}
      >
        INSUFFICIENT EVIDENCE
      </span>
    );
  }
  return (
    <span style={{ fontFamily: mono, fontSize: small ? 10.5 : 10, fontWeight: 600, color: "#fff", background: "#0a0a0b", padding: "3px 7px", borderRadius: 5, whiteSpace: "nowrap", alignSelf: "center" }}>
      {code}
    </span>
  );
}

function EmptyRow({ text }: { text: string }) {
  return (
    <div style={{ fontSize: 13, color: "var(--sub)", lineHeight: 1.5, padding: "6px 0" }}>{text}</div>
  );
}

function Card({ children, pad = "26px 28px" }: { children: React.ReactNode; pad?: string }) {
  return (
    <div style={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 12, padding: pad }}>
      {children}
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ fontFamily: mono, fontSize: 11, color: "var(--sub)", letterSpacing: ".08em", marginBottom: 16 }}>
      {children}
    </div>
  );
}

function FeedbackChoices({
  label,
  choices,
  selected,
  disabled,
  onChoose,
}: {
  label: string;
  choices: Array<[string, string]>;
  selected?: string;
  disabled?: boolean;
  onChoose: (value: string) => void;
}) {
  return (
    <div aria-label={label} style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 10 }}>
      {choices.map(([value, text]) => (
        <button
          key={value}
          type="button"
          aria-pressed={selected === value}
          disabled={disabled}
          onClick={() => onChoose(value)}
          style={{ border: `1px solid ${selected === value ? "var(--ink)" : "var(--line2)"}`, borderRadius: 6, padding: "5px 8px", background: selected === value ? "var(--ink)" : "var(--paper)", color: selected === value ? "var(--paper)" : "var(--sub)", font: "inherit", fontSize: 10.5, cursor: "pointer", opacity: disabled ? .55 : 1 }}
        >
          {text}
        </button>
      ))}
    </div>
  );
}
