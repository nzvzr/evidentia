"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import AppShell from "@/components/AppShell";
import DownloadDocxButton from "@/components/DownloadDocxButton";
import { generateReportForId } from "@/data/demoReports";
import { fetchBackendReport, fetchReportSourceAudit } from "@/lib/reportsApi";
import type { EvidentiaReport, ReportSourceAudit } from "@/lib/types";

const mono = "var(--font-plex-mono), monospace";

const SEV_COLORS: Record<"High" | "Medium" | "Low", string> = {
  High: "#c34635",
  Medium: "#c1852b",
  Low: "#8b8b91",
};

const INSUFFICIENT = "N/A";
const isInsufficient = (code: string) => (code || "").trim().toUpperCase() === INSUFFICIENT;

/** Agents refined by the LLM in full (llm-assisted) mode. */
const LLM_AGENTS = new Set([
  "Persona Modeler",
  "Risk Analyzer",
  "Citation Binder",
  "Playbook Composer",
  "Brief Synthesizer",
]);
/** Agents refined by the LLM in summary mode (single final call). */
const SUMMARY_LLM_AGENTS = new Set(["Persona Modeler", "Playbook Composer"]);
const EMPTY_SET = new Set<string>();

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
  const params = useParams<{ id: string }>();
  const id = (Array.isArray(params.id) ? params.id[0] : params.id) || "current";

  const [report, setReport] = useState<EvidentiaReport | null>(null);
  const [sourceAudit, setSourceAudit] = useState<ReportSourceAudit | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "missing">("loading");
  const [chartReady, setChartReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    // The backend is the only source of truth. A 404 means the report does not
    // exist *for this tenant* — we must NOT fall back to a locally cached or
    // locally generated report, which is how another account's data (or a fake
    // report) could be rendered as if it were real.
    (async () => {
      const [backendReport, audit] = await Promise.all([
        fetchBackendReport(id),
        fetchReportSourceAudit(id),
      ]);
      if (cancelled) return;
      if (backendReport) {
        setReport(backendReport);
        setSourceAudit(audit);
        setState("ready");
      } else {
        setState("missing");
      }
    })();
    const t = setTimeout(() => setChartReady(true), 160);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [id]);

  if (state !== "ready" || !report) {
    return (
      <AppShell active="reports">
        <div style={{ padding: 48, maxWidth: 560 }}>
          <h1 style={{ fontSize: 22, fontWeight: 700, letterSpacing: "-.02em", margin: 0 }}>
            {state === "loading" ? "Loading report…" : "Report not found"}
          </h1>
          {state === "missing" && (
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
  const llmAgentSet =
    mode === "llm-summary" ? SUMMARY_LLM_AGENTS : mode === "llm-assisted" ? LLM_AGENTS : EMPTY_SET;
  const bindingByCitation = new Map(
    (sourceAudit?.evidenceBindings ?? []).map((binding) => [binding.citationId, binding]),
  );

  const metricCards = [
    {
      k: "Documents",
      v: String(metrics.documentsAnalyzed),
      s: sourceAudit
        ? sourceAudit.corpusMode === "tenant"
          ? `${sourceAudit.sourceVersionCount} frozen versions`
          : "of 8 sample documents"
        : "corpus unavailable",
      accent: false,
    },
    { k: "Passages indexed", v: metrics.passagesIndexed.toLocaleString(), s: "semantic chunks", accent: false },
    { k: "Citations", v: String(metrics.citationsUsed), s: "source-traced", accent: false },
    { k: "Risks flagged", v: String(metrics.risksFlagged), s: severityBreakdown(report), accent: false },
    { k: "Confidence", v: `${report.confidence}%`, s: "grounding score", accent: true },
  ];

  return (
    <AppShell active="reports">
      {/* header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 28px", height: 60, background: "var(--paper)", borderBottom: "1px solid var(--line)", position: "sticky", top: 0, zIndex: 5 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
          <button onClick={() => router.push("/reports")} style={{ background: "transparent", border: "none", cursor: "pointer", font: "inherit", fontWeight: 700, fontSize: 14.5, color: "var(--ink)" }}>Reports</button>
          <span style={{ color: "var(--line2)" }}>/</span>
          <span style={{ fontSize: 13.5, color: "var(--sub)" }}>{report.company} · {report.market}</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
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

      <div style={{ maxWidth: 1240, width: "100%", margin: "0 auto", padding: "32px 40px 64px" }}>
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
                {sourceAudit
                  ? sourceAudit.corpusMode === "tenant"
                    ? "TENANT CORPUS"
                    : "SAMPLE CORPUS"
                  : "CORPUS UNAVAILABLE"}
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
            <div>7 AGENTS · {metrics.documentsAnalyzed} DOCS · CONFIDENCE {report.confidence}%</div>
          </div>
        </div>

        {/* metric cards */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(5,1fr)", gap: 1, background: "var(--line)", border: "1px solid var(--line)", borderRadius: 12, overflow: "hidden", marginBottom: 28 }} className="ev-metric-grid">
          {metricCards.map((m) => (
            <div key={m.k} style={{ padding: "20px 20px", background: "var(--panel)" }}>
              <div style={{ fontFamily: mono, fontSize: 10.5, color: "var(--sub)", letterSpacing: ".06em", textTransform: "uppercase" }}>{m.k}</div>
              <div style={{ fontSize: 27, fontWeight: 700, letterSpacing: "-.02em", marginTop: 9, color: m.accent ? "var(--accent)" : "var(--ink)" }}>{m.v}</div>
              <div style={{ fontSize: 11.5, color: "var(--sub)", marginTop: 4 }}>{m.s}</div>
            </div>
          ))}
        </div>

        {/* executive summary */}
        <div style={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 12, padding: "22px 26px", marginBottom: 28 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
            <span style={{ fontFamily: mono, fontSize: 11, color: "var(--sub)", letterSpacing: ".08em" }}>EXECUTIVE SUMMARY</span>
            <span style={{ flex: 1, height: 1, background: "var(--line)" }} />
          </div>
          <p style={{ fontSize: 15, lineHeight: 1.62, color: "var(--ink2)", margin: 0 }}>{report.summary}</p>
        </div>

        {/* two-column body */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 380px", gap: 28, alignItems: "start" }} className="ev-report-grid">
          {/* LEFT */}
          <div style={{ display: "flex", flexDirection: "column", gap: 28 }}>
            <Card>
              <SectionLabel>PERSONA BRIEF</SectionLabel>
              <p style={{ fontSize: 16, lineHeight: 1.62, color: "var(--ink2)", margin: 0 }}>{personaBrief.description}</p>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 20 }}>
                {personaBrief.priorities.map((p) => (
                  <span key={p} style={{ fontFamily: mono, fontSize: 11, color: "var(--ink)", background: "var(--shell)", border: "1px solid var(--line)", padding: "6px 11px", borderRadius: 6 }}>{p}</span>
                ))}
              </div>
            </Card>

            <Card>
              <SectionLabel>RECOMMENDED WORKFLOW</SectionLabel>
              {report.workflowSteps.length === 0 ? (
                <EmptyRow text="No workflow steps could be grounded in the selected documents." />
              ) : (
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
              )}
            </Card>

            <Card>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 18 }}>
                <span style={{ fontFamily: mono, fontSize: 11, color: "var(--sub)", letterSpacing: ".08em" }}>RISKS &amp; WARNINGS</span>
                <span style={{ fontFamily: mono, fontSize: 11, color: "var(--sub)" }}>{report.risks.length} flagged</span>
              </div>
              {report.risks.length === 0 ? (
                <EmptyRow text="No risks met the evidence-support threshold for this corpus." />
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  {report.risks.map((r) => {
                    const color = SEV_COLORS[r.severity] ?? SEV_COLORS.Low;
                    const insufficient = isInsufficient(r.evidenceCode);
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
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </Card>
          </div>

          {/* RIGHT */}
          <div style={{ display: "flex", flexDirection: "column", gap: 28 }}>
            <Card pad="24px 24px">
              <SectionLabel>AGENT TIMELINE</SectionLabel>
              <div style={{ display: "flex", flexDirection: "column" }}>
                {report.agentSteps.map((t) => (
                  <div key={t.agent} style={{ display: "flex", alignItems: "center", gap: 12, padding: "9px 0" }}>
                    <span style={{ width: 7, height: 7, borderRadius: "50%", background: "var(--accent)", flex: "none" }} />
                    <span style={{ fontSize: 13, color: "var(--ink)", flex: 1 }}>{t.agent}</span>
                    {llmAgentSet.has(t.agent) && (
                      <span style={{ fontFamily: mono, fontSize: 9, fontWeight: 600, letterSpacing: ".05em", color: "#fff", background: "var(--accent)", padding: "2px 6px", borderRadius: 4 }}>LLM</span>
                    )}
                    <span style={{ fontFamily: mono, fontSize: 11, color: "var(--sub)" }}>{t.duration}</span>
                  </div>
                ))}
              </div>
            </Card>

            <Card pad="24px 24px">
              <SectionLabel>DOCUMENT RELEVANCE</SectionLabel>
              <div style={{ display: "flex", flexDirection: "column", gap: 15 }}>
                {metrics.documentRelevance.map((d) => (
                  <div key={d.document}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                      <span style={{ fontSize: 12.5, color: "var(--ink)" }}>{d.document}</span>
                      <span style={{ fontFamily: mono, fontSize: 11.5, color: "var(--sub)" }}>{d.score}%</span>
                    </div>
                    <div style={{ height: 7, background: "var(--shell)", borderRadius: 4, overflow: "hidden" }}>
                      <div style={{ width: `${chartReady ? d.score : 0}%`, height: "100%", background: d.score >= 85 ? "var(--accent)" : "#0a0a0b", borderRadius: 4, transition: "width .8s cubic-bezier(.22,1,.36,1)" }} />
                    </div>
                  </div>
                ))}
              </div>
            </Card>

            <Card pad="24px 24px">
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
                <span style={{ fontFamily: mono, fontSize: 11, color: "var(--sub)", letterSpacing: ".08em" }}>CITATIONS</span>
                <span style={{ fontFamily: mono, fontSize: 11, color: "var(--sub)" }}>{report.citations.length} sources</span>
              </div>
              {report.citations.length === 0 ? (
                <EmptyRow text="No source citations were bound for this report." />
              ) : (
                <div style={{ display: "flex", flexDirection: "column" }}>
                  {report.citations.map((c, i) => (
                    <div key={c.id + i} style={{ display: "flex", gap: 12, padding: "13px 0", borderBottom: i < report.citations.length - 1 ? "1px solid var(--line)" : "none" }}>
                      <span style={{ fontFamily: mono, fontSize: 10.5, fontWeight: 600, color: "#fff", background: "#0a0a0b", padding: "3px 7px", borderRadius: 5, flex: "none", alignSelf: "flex-start", whiteSpace: "nowrap" }}>{c.id}</span>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 12.5, fontWeight: 600, color: "var(--ink)" }}>{c.source}</div>
                        {c.section && (
                          <div style={{ fontFamily: mono, fontSize: 10.5, color: "var(--sub)", marginTop: 2 }}>{c.section}</div>
                        )}
                        {bindingByCitation.get(c.id) && (
                          <div style={{ fontFamily: mono, fontSize: 10, color: "var(--sub)", marginTop: 3 }}>
                            VERSION {bindingByCitation.get(c.id)!.documentVersionId} · SECTION {bindingByCitation.get(c.id)!.sectionOrdinal + 1}
                          </div>
                        )}
                        <div style={{ fontSize: 12.5, color: "var(--ink2)", marginTop: 4, lineHeight: 1.5, fontStyle: "italic" }}>&ldquo;{c.excerpt}&rdquo;</div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </Card>

            {sourceAudit && (
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

            <div style={{ background: "#0a0a0b", color: "#f5f5f3", borderRadius: 12, padding: "24px 24px" }}>
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
            </div>
          </div>
        </div>
      </div>

      <style jsx global>{`
        @media (max-width: 1040px) {
          .ev-report-grid {
            grid-template-columns: 1fr !important;
          }
        }
        @media (max-width: 760px) {
          .ev-metric-grid {
            grid-template-columns: repeat(2, 1fr) !important;
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
