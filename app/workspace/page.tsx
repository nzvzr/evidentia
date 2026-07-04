"use client";

import { useRouter } from "next/navigation";
import AppShell from "@/components/AppShell";
import { DEMO_DOCS } from "@/lib/demoDocs";
import { MARKETS } from "@/lib/markets";
import { PERSONAS } from "@/lib/personas";
import type { DocId } from "@/lib/types";
import { useWorkspaceSelection } from "@/lib/useWorkspace";

const mono = "var(--font-plex-mono), monospace";

export default function WorkspacePage() {
  const router = useRouter();
  const { selection, setSelection, hydrated } = useWorkspaceSelection();

  const docsCount = selection.picked.length;
  const canRun =
    docsCount > 0 && !!selection.market && (!!selection.persona || !!selection.custom.trim());
  const nPassages = ((docsCount || 8) * 163).toLocaleString();

  const marketLabel = selection.market || "No market selected";
  const personaLabel = selection.persona
    ? PERSONAS.find((p) => p.id === selection.persona)?.title ?? "No persona selected"
    : selection.custom.trim() || "No persona selected";

  const toggleDoc = (id: DocId) => {
    const has = selection.picked.includes(id);
    setSelection({
      ...selection,
      picked: has ? selection.picked.filter((x) => x !== id) : [...selection.picked, id],
    });
  };

  const startRun = () => {
    if (!canRun) return;
    setSelection(selection);
    router.push("/running");
  };

  return (
    <AppShell active="workspace">
      {/* header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 28px", height: 60, background: "var(--paper)", borderBottom: "1px solid var(--line)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
          <span style={{ fontWeight: 700, fontSize: 14.5 }}>New workspace</span>
          <span style={{ color: "var(--line2)" }}>/</span>
          <span style={{ fontSize: 13.5, color: "var(--sub)" }}>Configure</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, fontFamily: mono, fontSize: 11, color: "var(--sub)" }} className="hidden sm:flex">
          <span style={{ color: "var(--ink)", fontWeight: 500 }}>1 · Configure</span>
          <span style={{ color: "var(--line2)" }}>›</span>
          <span>2 · Run</span>
          <span style={{ color: "var(--line2)" }}>›</span>
          <span>3 · Report</span>
        </div>
      </div>

      <div style={{ flex: 1, display: "grid", gridTemplateColumns: "1fr 320px", maxWidth: 1240, width: "100%", margin: "0 auto" }} className="ev-ws-grid">
        {/* main config */}
        <div style={{ padding: "38px 40px", borderRight: "1px solid var(--line)" }}>
          <h1 style={{ fontSize: 27, fontWeight: 700, letterSpacing: "-.02em", margin: 0 }}>
            Configure the workspace
          </h1>
          <p style={{ fontSize: 14.5, color: "var(--sub)", margin: "9px 0 0", lineHeight: 1.5 }}>
            Evidentia will model a persona, retrieve evidence across the selected corpus, and compose a cited report for your target market.
          </p>

          {/* STEP 1 docs */}
          <section style={{ marginTop: 38 }}>
            <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 16 }}>
              <div style={{ display: "flex", alignItems: "baseline", gap: 11 }}>
                <span style={{ fontFamily: mono, fontSize: 11, color: "var(--accent)", letterSpacing: ".06em" }}>STEP 01</span>
                <span style={{ fontSize: 16, fontWeight: 600 }}>Select documents</span>
              </div>
              <span style={{ fontFamily: mono, fontSize: 11.5, color: "var(--sub)" }}>
                {hydrated ? docsCount : "—"} of 8 selected
              </span>
            </div>
            <div style={{ border: "1px solid var(--line)", borderRadius: 11, overflow: "hidden", background: "var(--paper)" }}>
              {DEMO_DOCS.map((doc, i) => {
                const checked = hydrated && selection.picked.includes(doc.id);
                return (
                  <button
                    key={doc.id}
                    onClick={() => toggleDoc(doc.id)}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 14,
                      padding: "14px 16px",
                      cursor: "pointer",
                      width: "100%",
                      textAlign: "left",
                      font: "inherit",
                      borderBottom: i < DEMO_DOCS.length - 1 ? "1px solid var(--line)" : "none",
                      borderLeft: "none",
                      borderRight: "none",
                      borderTop: "none",
                      background: checked ? "var(--accent-weak)" : "var(--paper)",
                    }}
                  >
                    <span
                      style={{
                        width: 20,
                        height: 20,
                        flex: "none",
                        borderRadius: 5,
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        border: checked ? "none" : "1.5px solid var(--line2)",
                        background: checked ? "var(--accent)" : "transparent",
                      }}
                    >
                      {checked && <span style={{ color: "#fff", fontSize: 11, fontWeight: 700, lineHeight: 1 }}>✓</span>}
                    </span>
                    <span style={{ flex: 1, minWidth: 0 }}>
                      <span style={{ display: "block", fontSize: 14, fontWeight: 500, color: "var(--ink)" }}>{doc.name}</span>
                      <span style={{ display: "block", fontFamily: mono, fontSize: 11, color: "var(--sub)", marginTop: 3 }}>{doc.meta}</span>
                    </span>
                    <span style={{ fontFamily: mono, fontSize: 10.5, color: "var(--sub)", padding: "3px 8px", border: "1px solid var(--line)", borderRadius: 5 }}>{doc.kind}</span>
                  </button>
                );
              })}
            </div>
          </section>

          {/* STEP 2 market */}
          <section style={{ marginTop: 36 }}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 11, marginBottom: 16 }}>
              <span style={{ fontFamily: mono, fontSize: 11, color: "var(--accent)", letterSpacing: ".06em" }}>STEP 02</span>
              <span style={{ fontSize: 16, fontWeight: 600 }}>Choose a market</span>
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
              {MARKETS.map((m) => {
                const sel = selection.market === m;
                return (
                  <button
                    key={m}
                    onClick={() => setSelection({ ...selection, market: m })}
                    style={{
                      fontFamily: "inherit",
                      fontSize: 13.5,
                      fontWeight: sel ? 600 : 500,
                      cursor: "pointer",
                      padding: "10px 16px",
                      borderRadius: 8,
                      color: sel ? "#fff" : "var(--ink)",
                      background: sel ? "#0a0a0b" : "var(--paper)",
                      border: `1px solid ${sel ? "#0a0a0b" : "var(--line2)"}`,
                    }}
                  >
                    {m}
                  </button>
                );
              })}
            </div>
          </section>

          {/* STEP 3 persona */}
          <section style={{ marginTop: 36 }}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 11, marginBottom: 16 }}>
              <span style={{ fontFamily: mono, fontSize: 11, color: "var(--accent)", letterSpacing: ".06em" }}>STEP 03</span>
              <span style={{ fontSize: 16, fontWeight: 600 }}>Choose a persona</span>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 10 }} className="ev-persona-grid">
              {PERSONAS.map((p) => {
                const sel = selection.persona === p.id;
                return (
                  <button
                    key={p.id}
                    onClick={() => setSelection({ ...selection, persona: p.id, custom: "" })}
                    style={{
                      cursor: "pointer",
                      padding: "14px 15px",
                      borderRadius: 10,
                      textAlign: "left",
                      font: "inherit",
                      background: sel ? "var(--accent-weak)" : "var(--paper)",
                      border: `1px solid ${sel ? "var(--accent)" : "var(--line2)"}`,
                    }}
                  >
                    <div style={{ fontSize: 14, fontWeight: 600, color: "var(--ink)" }}>{p.title}</div>
                    <div style={{ fontSize: 12, color: "var(--sub)", marginTop: 5, lineHeight: 1.4 }}>{p.focus}</div>
                  </button>
                );
              })}
            </div>
            <div style={{ marginTop: 14 }}>
              <div style={{ fontSize: 12.5, color: "var(--sub)", marginBottom: 8 }}>Or describe your own role</div>
              <input
                value={selection.custom}
                onChange={(e) =>
                  setSelection({
                    ...selection,
                    custom: e.target.value,
                    persona: e.target.value.trim() ? "custom" : "",
                  })
                }
                placeholder="Field technician handling on-site equipment incidents..."
                style={{ width: "100%", fontFamily: "inherit", fontSize: 14, color: "var(--ink)", background: "var(--paper)", border: "1px solid var(--line2)", borderRadius: 9, padding: "12px 14px", outline: "none" }}
              />
            </div>
          </section>
        </div>

        {/* summary rail */}
        <aside style={{ padding: "38px 28px", background: "var(--paper)", position: "sticky", top: 0, alignSelf: "start" }}>
          <div style={{ fontFamily: mono, fontSize: 11, color: "var(--sub)", letterSpacing: ".08em", marginBottom: 20 }}>RUN SUMMARY</div>
          <div style={{ display: "flex", flexDirection: "column" }}>
            <SummaryRow label="Documents" value={String(hydrated ? docsCount : 0)} />
            <SummaryRow label="Market" value={marketLabel} />
            <SummaryRow label="Persona" value={personaLabel} />
            <SummaryRow label="Pipeline" value="7-stage agents" />
            <SummaryRow label="Output" value="Cited playbook" />
            <SummaryRow label="Mode" value="Demo corpus" />
            <SummaryRow label="Est. passages" value={nPassages} last />
          </div>
          <button
            onClick={startRun}
            disabled={!canRun}
            style={{
              width: "100%",
              marginTop: 22,
              fontFamily: "inherit",
              fontSize: 14.5,
              fontWeight: 600,
              padding: 14,
              borderRadius: 10,
              border: "none",
              cursor: canRun ? "pointer" : "not-allowed",
              color: canRun ? "#fff" : "#a7a7ac",
              background: canRun ? "#0a0a0b" : "#e6e6e3",
            }}
          >
            Run workflow →
          </button>
          <div style={{ fontSize: 11.5, color: "var(--sub)", textAlign: "center", marginTop: 12, lineHeight: 1.5 }}>
            {canRun ? "Ready — 7 agents will run in sequence." : "Select at least one document, a market, and a persona."}
          </div>
        </aside>
      </div>

      <style jsx global>{`
        @media (max-width: 960px) {
          .ev-ws-grid {
            grid-template-columns: 1fr !important;
          }
          .ev-persona-grid {
            grid-template-columns: repeat(2, 1fr) !important;
          }
        }
      `}</style>
    </AppShell>
  );
}

function SummaryRow({ label, value, last }: { label: string; value: string; last?: boolean }) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        gap: 12,
        padding: "13px 0",
        borderBottom: last ? "none" : "1px solid var(--line)",
      }}
    >
      <span style={{ fontSize: 13, color: "var(--sub)" }}>{label}</span>
      <span style={{ fontSize: 13, fontWeight: 600, textAlign: "right", maxWidth: "60%" }}>{value}</span>
    </div>
  );
}
