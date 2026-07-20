"use client";

import { useMemo } from "react";
import { useRouter } from "next/navigation";
import AppShell from "@/components/AppShell";
import { MARKETS } from "@/lib/markets";
import { PERSONAS } from "@/lib/personas";
import { sizeLabel, useTenantDocuments } from "@/lib/tenantDocuments";
import { useWorkspaceSelection } from "@/lib/useWorkspace";
import { buildAgentInput } from "@/lib/workspaceMapping";
import { writePendingRun } from "@/lib/pendingRun";

const mono = "var(--font-plex-mono), monospace";

export default function WorkspacePage() {
  const router = useRouter();
  const { selection, setSelection, hydrated: selectionHydrated } = useWorkspaceSelection();
  const {
    documents,
    corpus,
    corpusEnabled,
    loadError,
    hydrated: documentsHydrated,
  } = useTenantDocuments();

  const eligibleDocuments = useMemo(
    () =>
      documents.filter(
        (doc) =>
          doc.ingestion?.stage === "ready" &&
          doc.ingestion.finalized &&
          doc.ingestion.generationEligible,
      ),
    [documents],
  );
  const eligibleIds = useMemo(() => new Set(eligibleDocuments.map((doc) => doc.id)), [eligibleDocuments]);
  const selectedIds = selection.picked.filter((id) => eligibleIds.has(id));
  const docsCount = selectedIds.length;
  const readySectionCount = eligibleDocuments.reduce(
    (total, doc) => total + (doc.ingestion?.sectionCount ?? 0),
    0,
  );
  const selectedSectionCount = eligibleDocuments
    .filter((doc) => selectedIds.includes(doc.id))
    .reduce((total, doc) => total + (doc.ingestion?.sectionCount ?? 0), 0);
  const corpusReady = corpusEnabled && Boolean(corpus?.generationEnabled) && !loadError;
  const canRun =
    selectionHydrated &&
    documentsHydrated &&
    corpusReady &&
    docsCount > 0 &&
    Boolean(selection.market) &&
    Boolean(selection.persona || selection.custom.trim());

  const marketLabel = selection.market || "No market selected";
  const personaLabel = selection.persona
    ? ((PERSONAS.find((persona) => persona.id === selection.persona)?.title ??
      selection.custom.trim()) || "No persona selected")
    : selection.custom.trim() || "No persona selected";

  const toggleDocument = (id: string) => {
    const picked = selectedIds.includes(id)
      ? selectedIds.filter((selectedId) => selectedId !== id)
      : [...selectedIds, id];
    setSelection({ ...selection, picked });
  };

  const startRun = () => {
    if (!canRun) return;
    const currentSelection = { ...selection, picked: selectedIds };
    setSelection(currentSelection);
    writePendingRun(buildAgentInput(currentSelection));
    router.push("/running");
  };

  const emptyReason = loadError
    ? "The authenticated document service is unavailable."
    : !corpusEnabled
      ? "Tenant document ingestion is disabled for this deployment."
      : eligibleDocuments.length === 0
        ? "No Citation-ready tenant documents are available."
        : !corpus?.generationEnabled
          ? "Tenant report generation is disabled for this deployment."
          : "Select at least one document, a market, and a persona.";

  return (
    <AppShell active="workspace">
      <div style={headerBar}>
        <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
          <span style={{ fontWeight: 700, fontSize: 14.5 }}>New workspace</span>
          <span style={{ color: "var(--line2)" }}>/</span>
          <span style={{ fontSize: 13.5, color: "var(--sub)" }}>Configure</span>
        </div>
        <div style={{ display: "flex", gap: 8, fontFamily: mono, fontSize: 11, color: "var(--sub)" }} className="hidden sm:flex">
          <span style={{ color: "var(--ink)", fontWeight: 500 }}>1 · Configure</span>
          <span>›</span><span>2 · Run</span><span>›</span><span>3 · Report</span>
        </div>
      </div>

      <div style={{ flex: 1, display: "grid", gridTemplateColumns: "1fr 320px", maxWidth: 1240, width: "100%", margin: "0 auto" }} className="ev-ws-grid">
        <div style={{ padding: "38px 40px", borderRight: "1px solid var(--line)" }}>
          <h1 style={{ fontSize: 27, fontWeight: 700, letterSpacing: "-.02em", margin: 0 }}>Configure the workspace</h1>
          <p style={{ fontSize: 14.5, color: "var(--sub)", margin: "9px 0 0", lineHeight: 1.5 }}>
            Select finalized tenant evidence, then choose the market and reader persona for the persisted report.
          </p>

          <section style={{ marginTop: 38 }}>
            <div style={stepHeader}>
              <div style={{ display: "flex", alignItems: "baseline", gap: 11 }}>
                <StepNumber>STEP 01</StepNumber>
                <span style={{ fontSize: 16, fontWeight: 600 }}>Select Citation-ready documents</span>
              </div>
              <span style={{ fontFamily: mono, fontSize: 11.5, color: "var(--sub)" }}>
                {selectionHydrated && documentsHydrated ? `${docsCount} of ${eligibleDocuments.length} selected` : "—"}
              </span>
            </div>

            {documentsHydrated && eligibleDocuments.length === 0 ? (
              <div style={emptyPanel}>
                <div style={{ fontSize: 14, fontWeight: 600 }}>{emptyReason}</div>
                <button onClick={() => router.push("/documents")} style={{ ...ghostBtn, marginTop: 14 }}>
                  Go to Documents
                </button>
              </div>
            ) : (
              <div style={documentList}>
                {eligibleDocuments.map((doc, index) => {
                  const checked = selectionHydrated && selectedIds.includes(doc.id);
                  const ingestion = doc.ingestion;
                  return (
                    <button
                      key={`${doc.id}:v${ingestion?.versionNo ?? "current"}`}
                      onClick={() => toggleDocument(doc.id)}
                      style={{
                        ...documentButton,
                        borderBottom: index < eligibleDocuments.length - 1 ? "1px solid var(--line)" : "none",
                        background: checked ? "var(--accent-weak)" : "var(--paper)",
                      }}
                    >
                      <span style={{ ...checkbox, border: checked ? "none" : "1.5px solid var(--line2)", background: checked ? "var(--accent)" : "transparent" }}>
                        {checked && <span style={{ color: "#fff", fontSize: 11, fontWeight: 700 }}>✓</span>}
                      </span>
                      <span style={{ flex: 1, minWidth: 0 }}>
                        <span style={{ display: "block", fontSize: 14, fontWeight: 500 }}>{doc.title}</span>
                        <span style={{ display: "block", fontFamily: mono, fontSize: 11, color: "var(--sub)", marginTop: 3 }}>
                          {[
                            ingestion?.filename,
                            ingestion?.versionNo != null ? `v${ingestion.versionNo}` : null,
                            ingestion?.sectionCount != null ? `${ingestion.sectionCount} sections` : null,
                            ingestion?.byteSize != null ? sizeLabel(ingestion.byteSize) : null,
                          ].filter(Boolean).join(" · ")}
                        </span>
                      </span>
                      <span style={readyBadge}>CITATION-READY</span>
                    </button>
                  );
                })}
              </div>
            )}
          </section>

          <section style={{ marginTop: 36 }}>
            <div style={sectionHeading}><StepNumber>STEP 02</StepNumber><span style={{ fontSize: 16, fontWeight: 600 }}>Choose a market</span></div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
              {MARKETS.map((market) => {
                const selected = selection.market === market;
                return (
                  <button key={market} onClick={() => setSelection({ ...selection, market })} style={{ ...choiceButton, color: selected ? "#fff" : "var(--ink)", background: selected ? "#0a0a0b" : "var(--paper)", borderColor: selected ? "#0a0a0b" : "var(--line2)" }}>
                    {market}
                  </button>
                );
              })}
            </div>
          </section>

          <section style={{ marginTop: 36 }}>
            <div style={sectionHeading}><StepNumber>STEP 03</StepNumber><span style={{ fontSize: 16, fontWeight: 600 }}>Choose a persona</span></div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 10 }} className="ev-persona-grid">
              {PERSONAS.map((persona) => {
                const selected = selection.persona === persona.id;
                return (
                  <button key={persona.id} onClick={() => setSelection({ ...selection, persona: persona.id, custom: "" })} style={{ ...personaButton, background: selected ? "var(--accent-weak)" : "var(--paper)", borderColor: selected ? "var(--accent)" : "var(--line2)" }}>
                    <div style={{ fontSize: 14, fontWeight: 600 }}>{persona.title}</div>
                    <div style={{ fontSize: 12, color: "var(--sub)", marginTop: 5, lineHeight: 1.4 }}>{persona.focus}</div>
                  </button>
                );
              })}
            </div>
            <div style={{ marginTop: 14 }}>
              <div style={{ fontSize: 12.5, color: "var(--sub)", marginBottom: 8 }}>Or describe your own role</div>
              <input
                value={selection.custom}
                onChange={(event) => setSelection({ ...selection, custom: event.target.value, persona: event.target.value.trim() ? "custom" : "" })}
                placeholder="Field technician handling on-site equipment incidents..."
                style={customInput}
              />
            </div>
          </section>
        </div>

        <aside style={{ padding: "38px 28px", background: "var(--paper)", position: "sticky", top: 0, alignSelf: "start" }}>
          <div style={{ fontFamily: mono, fontSize: 11, color: "var(--sub)", letterSpacing: ".08em", marginBottom: 20 }}>RUN SUMMARY</div>
          <div style={{ display: "flex", flexDirection: "column" }}>
            <SummaryRow label="Selected" value={`${docsCount} documents`} />
            <SummaryRow label="Eligible corpus" value={`${eligibleDocuments.length} documents · ${readySectionCount} sections`} />
            <SummaryRow label="Selected evidence" value={`${selectedSectionCount} sections`} />
            <SummaryRow label="Market" value={marketLabel} />
            <SummaryRow label="Persona" value={personaLabel} />
            <SummaryRow label="Output" value="Persisted cited report" last />
          </div>
          <button onClick={startRun} disabled={!canRun} style={{ ...runButton, cursor: canRun ? "pointer" : "not-allowed", color: canRun ? "#fff" : "#a7a7ac", background: canRun ? "#0a0a0b" : "#e6e6e3" }}>
            Run workflow →
          </button>
          <div style={{ fontSize: 11.5, color: "var(--sub)", textAlign: "center", marginTop: 12, lineHeight: 1.5 }}>
            {canRun ? "Ready to generate from the selected tenant documents." : emptyReason}
          </div>
          {eligibleDocuments.length === 0 && documentsHydrated && (
            <button onClick={() => router.push("/documents")} style={{ ...ghostBtn, width: "100%", marginTop: 12 }}>Open Documents</button>
          )}
        </aside>
      </div>

      <style jsx global>{`
        @media (max-width: 960px) {
          .ev-ws-grid { grid-template-columns: 1fr !important; }
          .ev-persona-grid { grid-template-columns: repeat(2, 1fr) !important; }
        }
      `}</style>
    </AppShell>
  );
}

function StepNumber({ children }: { children: React.ReactNode }) {
  return <span style={{ fontFamily: mono, fontSize: 11, color: "var(--accent)", letterSpacing: ".06em" }}>{children}</span>;
}

function SummaryRow({ label, value, last }: { label: string; value: string; last?: boolean }) {
  return <div style={{ display: "flex", justifyContent: "space-between", gap: 12, padding: "13px 0", borderBottom: last ? "none" : "1px solid var(--line)" }}><span style={{ fontSize: 13, color: "var(--sub)" }}>{label}</span><span style={{ fontSize: 13, fontWeight: 600, textAlign: "right", maxWidth: "62%" }}>{value}</span></div>;
}

const headerBar: React.CSSProperties = { display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 28px", height: 60, background: "var(--paper)", borderBottom: "1px solid var(--line)" };
const stepHeader: React.CSSProperties = { display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 16, gap: 16 };
const sectionHeading: React.CSSProperties = { display: "flex", alignItems: "baseline", gap: 11, marginBottom: 16 };
const emptyPanel: React.CSSProperties = { padding: "28px", border: "1px solid var(--line)", borderRadius: 11, background: "var(--paper)", textAlign: "center", color: "var(--sub)" };
const documentList: React.CSSProperties = { border: "1px solid var(--line)", borderRadius: 11, overflow: "hidden", background: "var(--paper)" };
const documentButton: React.CSSProperties = { display: "flex", alignItems: "center", gap: 14, padding: "14px 16px", cursor: "pointer", width: "100%", textAlign: "left", font: "inherit", borderLeft: "none", borderRight: "none", borderTop: "none" };
const checkbox: React.CSSProperties = { width: 20, height: 20, flex: "none", borderRadius: 5, display: "flex", alignItems: "center", justifyContent: "center" };
const readyBadge: React.CSSProperties = { fontFamily: mono, fontSize: 9.5, color: "#207a4a", padding: "4px 8px", background: "rgba(32,122,74,.09)", borderRadius: 5 };
const choiceButton: React.CSSProperties = { fontFamily: "inherit", fontSize: 13.5, fontWeight: 500, cursor: "pointer", padding: "10px 16px", borderRadius: 8, border: "1px solid" };
const personaButton: React.CSSProperties = { cursor: "pointer", padding: "14px 15px", borderRadius: 10, textAlign: "left", font: "inherit", border: "1px solid" };
const customInput: React.CSSProperties = { width: "100%", fontFamily: "inherit", fontSize: 14, color: "var(--ink)", background: "var(--paper)", border: "1px solid var(--line2)", borderRadius: 9, padding: "12px 14px", outline: "none" };
const runButton: React.CSSProperties = { width: "100%", marginTop: 22, fontFamily: "inherit", fontSize: 14.5, fontWeight: 600, padding: 14, borderRadius: 10, border: "none" };
const ghostBtn: React.CSSProperties = { fontFamily: "inherit", fontSize: 13, fontWeight: 500, color: "var(--ink)", background: "var(--paper)", border: "1px solid var(--line2)", padding: "9px 15px", borderRadius: 8, cursor: "pointer" };
