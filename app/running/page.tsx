"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import AppShell from "@/components/AppShell";
import { AGENTS } from "@/lib/demoReport";
import { runEvidentiaAgents } from "@/lib/agents/orchestrator";
import { readPendingRun } from "@/lib/pendingRun";
import { buildAgentInput } from "@/lib/workspaceMapping";
import { readSelection } from "@/lib/useWorkspace";
import { saveReport } from "@/lib/reportsStore";
import type { AgentInput, EvidentiaReport } from "@/lib/types";

const mono = "var(--font-plex-mono), monospace";

// Stage cadence is presentational (a single request can't stream per-agent
// progress); completion is gated on the *actual* report, never on the timer.
const STAGE_MS = 780;
const SLOW_AFTER_MS = 22000; // surface a "taking longer" notice
const HARD_TIMEOUT_MS = 60000; // guarantee a result via the local pipeline
const FETCH_ABORT_MS = 45000; // stop waiting on the network, fall back locally

type Phase = "running" | "finalizing" | "slow" | "fallback" | "error";

export default function RunningPage() {
  const router = useRouter();
  const [stageIdx, setStageIdx] = useState(0);
  const [phase, setPhase] = useState<Phase>("running");
  const [reportReady, setReportReady] = useState(false);
  const [meta, setMeta] = useState({ personaLabel: "Persona", marketLabel: "Market" });

  useEffect(() => {
    const input: AgentInput = readPendingRun() ?? buildAgentInput(readSelection());
    const personaLabel = input.customPersona?.trim() ? input.customPersona.trim() : input.persona || "Persona";
    setMeta({ personaLabel, marketLabel: input.market || "Market" });

    const total = AGENTS.length;
    let report: EvidentiaReport | null = null;
    let stagesDone = false;
    let navigated = false;
    let usedFallback = false;

    const timers: Array<ReturnType<typeof setTimeout>> = [];
    let stageTimer: ReturnType<typeof setInterval> | null = null;

    const localFallback = (): EvidentiaReport => {
      usedFallback = true;
      return runEvidentiaAgents(input, { generatedAt: new Date().toISOString() });
    };

    const markReady = () => {
      if (report) setReportReady(true);
    };

    const finish = () => {
      if (navigated || !report || !stagesDone) return;
      navigated = true;
      if (stageTimer) clearInterval(stageTimer);
      timers.forEach(clearTimeout);
      try {
        saveReport(report);
      } catch {
        /* ignore quota errors */
      }
      router.push(`/reports/${report.id}`);
    };

    // 1) generate: backend/API first, deterministic local pipeline as fallback.
    const controller = new AbortController();
    const abortTimer = setTimeout(() => controller.abort(), FETCH_ABORT_MS);
    timers.push(abortTimer);

    (async () => {
      try {
        const res = await fetch("/api/generate-workflow", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(input),
          signal: controller.signal,
        });
        if (!res.ok) throw new Error(`status ${res.status}`);
        report = (await res.json()) as EvidentiaReport;
      } catch {
        try {
          report = localFallback();
        } catch {
          setPhase("error");
          return;
        }
      } finally {
        clearTimeout(abortTimer);
      }
      markReady();
      if (usedFallback && !navigated) setPhase((p) => (p === "error" ? p : "fallback"));
      finish();
    })();

    // 2) advance the visible pipeline stages (holds on the final stage).
    stageTimer = setInterval(() => {
      setStageIdx((prev) => {
        const next = prev + 1;
        if (next >= total - 1) {
          if (stageTimer) clearInterval(stageTimer);
          stagesDone = true;
          setPhase((p) => (p === "error" ? p : report ? "running" : "finalizing"));
          finish();
          return total - 1;
        }
        return next;
      });
    }, STAGE_MS);

    // 3) honest long-running + hard-timeout handling.
    timers.push(
      setTimeout(() => {
        if (!report && !navigated) setPhase((p) => (p === "error" ? p : "slow"));
      }, SLOW_AFTER_MS),
    );
    timers.push(
      setTimeout(() => {
        if (!report && !navigated) {
          try {
            report = localFallback();
            markReady();
            setPhase("fallback");
            stagesDone = true;
            finish();
          } catch {
            setPhase("error");
          }
        }
      }, HARD_TIMEOUT_MS),
    );

    return () => {
      if (stageTimer) clearInterval(stageTimer);
      timers.forEach(clearTimeout);
      controller.abort();
    };
  }, [router]);

  const total = AGENTS.length;
  const lastStage = stageIdx >= total - 1;

  const statusText =
    phase === "error" ? "● FAILED" : phase === "slow" ? "● STILL WORKING" : "● RUNNING";
  const statusColor = phase === "error" ? "#c34635" : "var(--accent)";

  const headline =
    phase === "error"
      ? "Generation failed"
      : phase === "fallback"
        ? "Finalizing offline report"
        : "Composing your report";

  const subline =
    phase === "error"
      ? "The report could not be generated. Please try again."
      : phase === "slow"
        ? "This is taking longer than usual — still analyzing the corpus. We'll finalize with the deterministic pipeline if needed."
        : phase === "fallback"
          ? "The AI backend was unavailable, so Evidentia is using its deterministic pipeline. The report is still fully grounded and cited."
          : phase === "finalizing"
            ? "Agents complete — compiling the grounded playbook…"
            : `Stage ${Math.min(stageIdx + 1, total)} of ${total} · ${AGENTS[Math.min(stageIdx, total - 1)].name}`;

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
          <span style={{ fontFamily: mono, fontSize: 11.5, color: statusColor }}>{statusText}</span>
        </div>

        <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", padding: 40 }}>
          <div style={{ width: "100%", maxWidth: 680 }}>
            <div style={{ fontFamily: mono, fontSize: 12, letterSpacing: ".2em", color: "rgba(245,245,243,.4)", textTransform: "uppercase" }}>
              Multi-agent workflow
            </div>
            <h2 style={{ fontSize: 26, fontWeight: 700, letterSpacing: "-.02em", margin: "12px 0 4px" }}>{headline}</h2>
            <div style={{ fontFamily: mono, fontSize: 13, color: "rgba(245,245,243,.55)", lineHeight: 1.5 }}>{subline}</div>

            {/* stage-segmented indicator (reflects completed pipeline stages, not a synthetic %) */}
            <div style={{ display: "flex", gap: 5, margin: "26px 0 30px" }}>
              {AGENTS.map((a, i) => {
                const done = phase !== "error" && (lastStage ? (i < total - 1 || reportReady) : i < stageIdx);
                const active = phase !== "error" && !done && i === stageIdx;
                return (
                  <div
                    key={a.id}
                    style={{
                      flex: 1,
                      height: 4,
                      borderRadius: 2,
                      background: done ? "var(--accent)" : active ? "rgba(47,86,224,.45)" : "rgba(255,255,255,.12)",
                      transition: "background .3s ease",
                    }}
                  />
                );
              })}
            </div>

            {phase === "error" ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 14, alignItems: "flex-start" }}>
                <div style={{ fontSize: 13.5, color: "rgba(245,245,243,.7)", lineHeight: 1.6 }}>
                  Something went wrong while generating this report.
                </div>
                <div style={{ display: "flex", gap: 10 }}>
                  <button onClick={() => window.location.reload()} style={btnPrimary}>Try again</button>
                  <button onClick={() => router.push("/workspace")} style={btnGhost}>Back to workspace</button>
                </div>
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                {AGENTS.map((a, i) => {
                  const isDone = lastStage ? (i < total - 1 || reportReady) : i < stageIdx;
                  const isActive = !isDone && i === stageIdx;
                  const isPending = !isDone && !isActive;
                  const stateText = isDone ? "Complete" : isActive ? "Running" : "Queued";
                  return (
                    <div
                      key={a.id}
                      style={{ display: "flex", alignItems: "flex-start", gap: 14, padding: "14px 4px", borderBottom: "1px solid rgba(255,255,255,.07)", opacity: isPending ? 0.5 : 1, transition: "opacity .3s" }}
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
                      <span style={{ fontFamily: mono, fontSize: 10.5, letterSpacing: ".05em", alignSelf: "center", color: isDone ? "var(--accent)" : isActive ? "#f5f5f3" : "rgba(245,245,243,.35)" }}>
                        {stateText}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </div>
    </AppShell>
  );
}

const btnPrimary: React.CSSProperties = {
  fontFamily: "inherit", fontSize: 13.5, fontWeight: 600, color: "#0a0a0b", background: "#fff",
  border: "none", padding: "10px 18px", borderRadius: 9, cursor: "pointer",
};
const btnGhost: React.CSSProperties = {
  fontFamily: "inherit", fontSize: 13.5, fontWeight: 500, color: "#f5f5f3", background: "transparent",
  border: "1px solid rgba(255,255,255,.2)", padding: "10px 18px", borderRadius: 9, cursor: "pointer",
};
