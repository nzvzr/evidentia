"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import AppShell from "@/components/AppShell";
import { AGENTS } from "@/lib/demoReport";
import { createPendingRun, readPendingRun, writePendingRun, type PendingRun } from "@/lib/pendingRun";
import { buildAgentInput } from "@/lib/workspaceMapping";
import { DEFAULT_SELECTION, readSelection } from "@/lib/useWorkspace";
import { acquireGeneration } from "@/lib/workflowGeneration";

const mono = "var(--font-plex-mono), monospace";

// Stage cadence is presentational (a single request can't stream per-agent
// progress); completion is gated on the *actual* report, never on the timer.
const STAGE_MS = 780;
const SLOW_AFTER_MS = 22000; // surface a "taking longer" notice

// /running is statically prerendered, so the server HTML can only ever carry
// the labels derived from the default workspace selection.
const DEFAULT_LABEL_INPUT = buildAgentInput(DEFAULT_SELECTION);

// Hydration detector: the store never changes, so this reads `false` exactly
// once — during server rendering and the matching hydration render.
const noopSubscribe = () => () => {};
const useHydrated = () =>
  useSyncExternalStore(
    noopSubscribe,
    () => true,
    () => false,
  );

/**
 * There is deliberately no local-pipeline fallback here any more.
 *
 * This report belongs to the signed-in account and is persisted to their tenant.
 * Generating it locally when the backend is unreachable would produce an
 * authenticated-looking report for a session nobody validated. If the server
 * cannot generate it, we say so and offer a retry.
 */
type Phase = "running" | "finalizing" | "slow" | "success" | "unavailable" | "limited" | "expired" | "empty" | "disabled" | "error";

const isTerminal = (phase: Phase) =>
  phase === "error" || phase === "unavailable" || phase === "limited" || phase === "expired" || phase === "empty" || phase === "disabled";

export default function RunningPage() {
  const router = useRouter();
  const [run, setRun] = useState<PendingRun>(() =>
    readPendingRun() ?? createPendingRun(buildAgentInput(readSelection())),
  );
  const [stageIdx, setStageIdx] = useState(0);
  const [phase, setPhase] = useState<Phase>("running");
  const [reportId, setReportId] = useState<string | null>(null);
  const [animationComplete, setAnimationComplete] = useState(false);
  const activeRunRef = useRef(run.id);
  const navigatedRef = useRef(false);
  const loginRedirectedRef = useRef(false);

  // The header labels come from browser storage, but the prerendered server
  // HTML can only contain the default selection, so rendering the stored
  // labels during the hydration render would mismatch it. Labels therefore
  // stay on the defaults until hydration completes. Only the *labels* wait:
  // `run` (above) is initialized from storage on the client immediately, and
  // effects never run on the server, so the generation effect always POSTs
  // the actual stored input — the post-hydration label re-render starts no
  // second request.
  const hydrated = useHydrated();

  const labelInput = hydrated ? run.input : DEFAULT_LABEL_INPUT;
  const personaLabel = labelInput.customPersona?.trim()
    ? labelInput.customPersona.trim()
    : labelInput.persona || "Persona";
  const marketLabel = labelInput.market || "Market";

  useEffect(() => {
    activeRunRef.current = run.id;
    let subscribed = true;
    const total = AGENTS.length;
    let visibleStage = 0;
    let requestPending = true;
    let stageTimer: ReturnType<typeof setInterval> | null = null;
    let slowTimer: ReturnType<typeof setTimeout> | null = null;

    const ownsRun = () => subscribed && activeRunRef.current === run.id;
    const generation = acquireGeneration(run);

    (async () => {
      const result = await generation.promise;
      requestPending = false;
      if (!ownsRun() || result.kind === "cancelled") return;
      if (slowTimer) clearTimeout(slowTimer);

      if (result.kind === "success") {
        setReportId(result.report.id);
        setPhase((current) => (isTerminal(current) ? current : "success"));
        return;
      }

      if (stageTimer) clearInterval(stageTimer);
      setPhase(result.kind);
    })();

    // Presentational only: the backend does not stream individual agent progress.
    stageTimer = setInterval(() => {
      if (!ownsRun()) return;
      visibleStage = Math.min(visibleStage + 1, total - 1);
      setStageIdx(visibleStage);
      if (visibleStage === total - 1) {
        if (stageTimer) clearInterval(stageTimer);
        setAnimationComplete(true);
        setPhase((current) => (isTerminal(current) || current === "success" ? current : "finalizing"));
      }
    }, STAGE_MS);

    slowTimer = setTimeout(() => {
      if (ownsRun() && requestPending) {
        setPhase((current) => (isTerminal(current) || current === "success" ? current : "slow"));
      }
    }, SLOW_AFTER_MS);

    return () => {
      subscribed = false;
      if (stageTimer) clearInterval(stageTimer);
      if (slowTimer) clearTimeout(slowTimer);
      generation.release();
    };
  }, [run]);

  // Successful navigation is deliberately isolated from request and animation
  // callbacks. The backend has already persisted the report at this point.
  useEffect(() => {
    if (!reportId || !animationComplete || isTerminal(phase) || navigatedRef.current) return;
    navigatedRef.current = true;
    router.push(`/reports/${reportId}`);
  }, [animationComplete, phase, reportId, router]);

  useEffect(() => {
    if (phase !== "expired" || loginRedirectedRef.current) return;
    loginRedirectedRef.current = true;
    router.push("/login?next=/workspace");
  }, [phase, router]);

  const retry = () => {
    const nextRun = writePendingRun(run.input);
    activeRunRef.current = nextRun.id;
    navigatedRef.current = false;
    loginRedirectedRef.current = false;
    setStageIdx(0);
    setPhase("running");
    setReportId(null);
    setAnimationComplete(false);
    setRun(nextRun);
  };

  const total = AGENTS.length;
  const lastStage = stageIdx >= total - 1;

  const failed =
    phase === "error" || phase === "unavailable" || phase === "limited" || phase === "expired" || phase === "empty" || phase === "disabled";

  const statusText = failed
    ? phase === "limited"
      ? "● RATE LIMITED"
      : "● FAILED"
    : phase === "slow"
      ? "● STILL WORKING"
      : "● RUNNING";
  const statusColor = failed ? "#c34635" : "var(--accent)";

  const headline =
    phase === "unavailable"
      ? "Generation unavailable"
      : phase === "empty"
        ? "No citation-ready documents"
        : phase === "disabled"
          ? "Tenant generation disabled"
      : phase === "limited"
        ? "Generation limit reached"
        : phase === "error"
          ? "Generation failed"
          : "Composing your report";

  const subline =
    phase === "unavailable"
      ? "The report service could not be reached, so we haven't generated anything. Your documents and reports are untouched — please try again in a moment."
      : phase === "empty"
        ? "Finalize at least one eligible document before generating a tenant report."
        : phase === "disabled"
          ? "Tenant report generation is not enabled for this deployment. Sample evidence was not substituted."
      : phase === "limited"
        ? "You've reached the report generation limit for now. Please try again later."
        : phase === "error"
          ? "The report could not be generated. Please try again."
          : phase === "slow"
            ? "This is taking longer than usual — still analyzing the corpus."
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
              {personaLabel} · {marketLabel}
            </span>
          </div>
          <span style={{ fontFamily: mono, fontSize: 11.5, color: statusColor }}>{statusText}</span>
        </div>

        <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", padding: 40 }}>
          <div style={{ width: "100%", maxWidth: 680 }}>
            <div style={{ fontFamily: mono, fontSize: 12, letterSpacing: ".2em", color: "rgba(245,245,243,.4)", textTransform: "uppercase" }}>
              Multi-agent workflow · Tenant corpus
            </div>
            <h2 style={{ fontSize: 26, fontWeight: 700, letterSpacing: "-.02em", margin: "12px 0 4px" }}>{headline}</h2>
            <div style={{ fontFamily: mono, fontSize: 13, color: "rgba(245,245,243,.55)", lineHeight: 1.5 }}>{subline}</div>

            {/* stage-segmented indicator (reflects completed pipeline stages, not a synthetic %) */}
            <div style={{ display: "flex", gap: 5, margin: "26px 0 30px" }}>
              {AGENTS.map((a, i) => {
                const done = !failed && (lastStage ? (i < total - 1 || !!reportId) : i < stageIdx);
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

            {failed ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 14, alignItems: "flex-start" }}>
                <div style={{ fontSize: 13.5, color: "rgba(245,245,243,.7)", lineHeight: 1.6 }}>
                  {phase === "unavailable"
                    ? "Nothing was generated and nothing was saved. This is a temporary server problem, not a problem with your documents."
                    : phase === "empty"
                      ? "No eligible tenant evidence was available. Nothing was generated or saved."
                    : phase === "disabled"
                      ? "Nothing was generated or saved, and the sample corpus was not used."
                    : phase === "limited"
                      ? "You've generated a lot of reports recently. The limit resets automatically."
                      : "Something went wrong while generating this report."}
                </div>
                <div style={{ display: "flex", gap: 10 }}>
                  {phase === "empty" ? (
                    <button onClick={() => router.push("/documents")} style={btnPrimary}>Go to Documents</button>
                  ) : (
                    <button onClick={retry} style={btnPrimary}>Try again</button>
                  )}
                  <button onClick={() => router.push("/workspace")} style={btnGhost}>Back to workspace</button>
                </div>
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                {AGENTS.map((a, i) => {
                  const isDone = lastStage ? (i < total - 1 || !!reportId) : i < stageIdx;
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
