"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import AppShell from "@/components/AppShell";
import { AGENTS } from "@/lib/demoReport";
import { PERSONAS } from "@/lib/personas";
import { readSelection } from "@/lib/useWorkspace";

const mono = "var(--font-plex-mono), monospace";
const STAGE_MS = 850; // ~6s total across 7 agents + compile

export default function RunningPage() {
  const router = useRouter();
  const [runIdx, setRunIdx] = useState(0);
  const [runDone, setRunDone] = useState(false);
  const [meta, setMeta] = useState({ personaLabel: "Persona", marketLabel: "Market" });
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    const sel = readSelection();
    const personaLabel = sel.persona
      ? sel.persona === "custom"
        ? sel.custom.trim() || "Custom Role"
        : PERSONAS.find((p) => p.id === sel.persona)?.title ?? "Persona"
      : sel.custom.trim() || "Persona";
    setMeta({ personaLabel, marketLabel: sel.market || "Market" });

    timer.current = setInterval(() => {
      setRunIdx((prev) => {
        const next = prev + 1;
        if (next >= AGENTS.length) {
          if (timer.current) clearInterval(timer.current);
          setRunDone(true);
          setTimeout(() => router.push("/reports/current"), 900);
          return AGENTS.length;
        }
        return next;
      });
    }, STAGE_MS);

    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [router]);

  const total = AGENTS.length;
  const pct = runDone ? 100 : Math.round((runIdx / total) * 100);
  const runProgressLabel = runDone
    ? "Compiling report…"
    : `Stage ${Math.min(runIdx + 1, total)} of ${total} · ${pct}% complete`;
  const runStatusText = runDone ? "● COMPILING" : "● RUNNING";

  return (
    <AppShell active="workspace" theme="dark" background="#0a0a0b">
      <div style={{ color: "#f5f5f3", flex: 1, display: "flex", flexDirection: "column" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 28px", height: 60, borderBottom: "1px solid rgba(255,255,255,.09)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
            <span style={{ fontWeight: 700, fontSize: 14.5 }}>Running workflow</span>
            <span style={{ color: "rgba(255,255,255,.25)" }}>/</span>
            <span style={{ fontSize: 13.5, color: "rgba(245,245,243,.6)" }}>
              {meta.personaLabel} · {meta.marketLabel}
            </span>
          </div>
          <span style={{ fontFamily: mono, fontSize: 11.5, color: "var(--accent)" }}>{runStatusText}</span>
        </div>

        <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", padding: 40 }}>
          <div style={{ width: "100%", maxWidth: 680 }}>
            <div style={{ fontFamily: mono, fontSize: 12, letterSpacing: ".2em", color: "rgba(245,245,243,.4)", textTransform: "uppercase" }}>
              Multi-agent workflow
            </div>
            <h2 style={{ fontSize: 26, fontWeight: 700, letterSpacing: "-.02em", margin: "12px 0 4px" }}>
              Composing your report
            </h2>
            <div style={{ fontFamily: mono, fontSize: 13, color: "rgba(245,245,243,.55)" }}>{runProgressLabel}</div>
            <div style={{ fontSize: 12.5, color: "rgba(245,245,243,.38)", marginTop: 8 }}>
              Each agent contributes a structured section to the final playbook.
            </div>

            <div style={{ height: 3, background: "rgba(255,255,255,.1)", borderRadius: 2, margin: "26px 0 30px", overflow: "hidden" }}>
              <div style={{ width: `${pct}%`, height: "100%", background: "var(--accent)", borderRadius: 2, transition: "width .5s ease" }} />
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
              {AGENTS.map((a, i) => {
                const isDone = runDone || i < runIdx;
                const isActive = !runDone && i === runIdx;
                const isPending = !isDone && !isActive;
                const statusText = isDone ? "Complete" : isActive ? "Running" : "Queued";
                return (
                  <div
                    key={a.id}
                    style={{
                      display: "flex",
                      alignItems: "flex-start",
                      gap: 14,
                      padding: "14px 4px",
                      borderBottom: "1px solid rgba(255,255,255,.07)",
                      opacity: isPending ? 0.5 : 1,
                      transition: "opacity .3s",
                    }}
                  >
                    <div style={{ width: 26, display: "flex", justifyContent: "center", paddingTop: 2 }}>
                      {isDone && (
                        <span style={{ width: 18, height: 18, borderRadius: "50%", background: "var(--accent)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 10, color: "#fff", fontWeight: 700 }}>✓</span>
                      )}
                      {isActive && (
                        <span className="ev-spin" style={{ width: 16, height: 16, borderRadius: "50%", border: "2px solid rgba(255,255,255,.2)", borderTopColor: "var(--accent)" }} />
                      )}
                      {isPending && (
                        <span style={{ width: 7, height: 7, borderRadius: "50%", background: "rgba(255,255,255,.22)", marginTop: 5 }} />
                      )}
                    </div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 15, fontWeight: 600, color: isPending ? "rgba(245,245,243,.7)" : "#f5f5f3" }}>{a.name}</div>
                      {(isDone || isActive) && (
                        <div style={{ fontFamily: mono, fontSize: 11.5, color: "rgba(245,245,243,.42)", marginTop: 3 }}>{a.log}</div>
                      )}
                    </div>
                    <span
                      style={{
                        fontFamily: mono,
                        fontSize: 10.5,
                        letterSpacing: ".05em",
                        alignSelf: "center",
                        color: isDone ? "var(--accent)" : isActive ? "#f5f5f3" : "rgba(245,245,243,.35)",
                      }}
                    >
                      {statusText}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
