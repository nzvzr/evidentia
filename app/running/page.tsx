"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import AppShell from "@/components/AppShell";
import { createPendingRun, readPendingRun, writePendingRun, type PendingRun } from "@/lib/pendingRun";
import { buildAgentInput } from "@/lib/workspaceMapping";
import { DEFAULT_SELECTION, readSelection } from "@/lib/useWorkspace";
import { acquireGeneration } from "@/lib/workflowGeneration";

const mono = "var(--font-plex-mono), monospace";
const SLOW_AFTER_MS = 22_000;
const DEFAULT_LABEL_INPUT = buildAgentInput(DEFAULT_SELECTION);
const noopSubscribe = () => () => {};
const useHydrated = () => useSyncExternalStore(noopSubscribe, () => true, () => false);

type Phase =
  | "running"
  | "slow"
  | "success"
  | "unavailable"
  | "limited"
  | "expired"
  | "empty"
  | "disabled"
  | "error";

const isFailure = (phase: Phase) =>
  phase === "error" ||
  phase === "unavailable" ||
  phase === "limited" ||
  phase === "expired" ||
  phase === "empty" ||
  phase === "disabled";

export default function RunningPage() {
  const router = useRouter();
  const [run, setRun] = useState<PendingRun>(() =>
    readPendingRun() ?? createPendingRun(buildAgentInput(readSelection())),
  );
  const [phase, setPhase] = useState<Phase>(
    run.input.selectedDocumentIds.length > 0 ? "running" : "empty",
  );
  const activeRunRef = useRef(run.id);
  const navigatedRef = useRef(false);
  const loginRedirectedRef = useRef(false);
  const routerRef = useRef(router);
  const hydrated = useHydrated();

  useEffect(() => {
    routerRef.current = router;
  }, [router]);

  const labelInput = hydrated ? run.input : DEFAULT_LABEL_INPUT;
  const personaLabel = labelInput.customPersona?.trim()
    ? labelInput.customPersona.trim()
    : labelInput.persona || "Persona";
  const marketLabel = labelInput.market || "Market";

  useEffect(() => {
    activeRunRef.current = run.id;
    if (run.input.selectedDocumentIds.length === 0) {
      return;
    }

    let subscribed = true;
    const ownsRun = () => subscribed && activeRunRef.current === run.id;
    const generation = acquireGeneration(run);
    const slowTimer = setTimeout(() => {
      if (ownsRun()) setPhase((current) => (isFailure(current) ? current : "slow"));
    }, SLOW_AFTER_MS);

    void generation.promise.then((result) => {
      if (!ownsRun() || result.kind === "cancelled") return;
      clearTimeout(slowTimer);
      if (result.kind === "success") {
        setPhase("success");
        if (!navigatedRef.current) {
          navigatedRef.current = true;
          routerRef.current.push(`/reports/${result.report.id}`);
        }
        return;
      }
      setPhase(result.kind);
    });

    return () => {
      subscribed = false;
      clearTimeout(slowTimer);
      generation.release();
    };
  }, [run]);

  useEffect(() => {
    if (phase !== "expired" || loginRedirectedRef.current) return;
    loginRedirectedRef.current = true;
    routerRef.current.push("/login?next=/workspace");
  }, [phase]);

  const retry = () => {
    const nextRun = writePendingRun(run.input);
    activeRunRef.current = nextRun.id;
    navigatedRef.current = false;
    loginRedirectedRef.current = false;
    setPhase("running");
    setRun(nextRun);
  };

  const failed = isFailure(phase);
  const statusText = failed
    ? phase === "limited"
      ? "● RATE LIMITED"
      : "● FAILED"
    : phase === "slow"
      ? "● STILL WORKING"
      : phase === "success"
        ? "● SAVED"
        : "● RUNNING";

  const headline =
    phase === "unavailable"
      ? "Generation unavailable"
      : phase === "empty"
        ? "No Citation-ready documents selected"
        : phase === "disabled"
          ? "Tenant generation disabled"
          : phase === "limited"
            ? "Generation limit reached"
            : phase === "error"
              ? "Generation failed"
              : phase === "success"
                ? "Report saved"
                : "Composing your report";

  const subline =
    phase === "unavailable"
      ? "The report service could not be reached. Nothing was generated or saved."
      : phase === "empty"
        ? "Select at least one finalized, generation-eligible tenant document before running."
        : phase === "disabled"
          ? "Tenant report generation is not enabled for this deployment."
          : phase === "limited"
            ? "You have reached the report generation limit for now. Please try again later."
            : phase === "error"
              ? "The report could not be generated. Please try again."
              : phase === "slow"
                ? "This is taking longer than usual. The backend is still processing the selected corpus."
                : phase === "success"
                  ? "The persisted report is ready. Opening it now…"
                  : "The authenticated backend is analyzing the selected tenant evidence. Progress details are unavailable until it completes.";

  return (
    <AppShell active="workspace" theme="dark" background="#0a0a0b">
      <div style={{ color: "#f5f5f3", flex: 1, display: "flex", flexDirection: "column" }}>
        <div style={headerBar}>
          <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
            <span style={{ fontWeight: 700, fontSize: 14.5 }}>Running workflow</span>
            <span style={{ color: "rgba(255,255,255,.25)" }}>/</span>
            <span style={{ fontSize: 13.5, color: "rgba(245,245,243,.6)" }}>
              {personaLabel} · {marketLabel}
            </span>
          </div>
          <span style={{ fontFamily: mono, fontSize: 11.5, color: failed ? "#c34635" : "var(--accent)" }}>
            {statusText}
          </span>
        </div>

        <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", padding: 40 }}>
          <div style={{ width: "100%", maxWidth: 680 }}>
            <div style={{ fontFamily: mono, fontSize: 12, letterSpacing: ".2em", color: "rgba(245,245,243,.4)", textTransform: "uppercase" }}>
              Authenticated generation · Tenant corpus
            </div>
            <h2 style={{ fontSize: 26, fontWeight: 700, letterSpacing: "-.02em", margin: "12px 0 4px" }}>{headline}</h2>
            <div style={{ fontFamily: mono, fontSize: 13, color: "rgba(245,245,243,.55)", lineHeight: 1.6 }}>{subline}</div>

            {!failed && phase !== "success" && (
              <div aria-label="Generation in progress" style={{ margin: "30px 0", height: 4, overflow: "hidden", borderRadius: 2, background: "rgba(255,255,255,.12)" }}>
                <div className="ev-indeterminate" style={{ width: "36%", height: "100%", borderRadius: 2, background: "var(--accent)" }} />
              </div>
            )}

            {failed && (
              <div style={{ display: "flex", flexDirection: "column", gap: 14, alignItems: "flex-start", marginTop: 28 }}>
                <div style={{ fontSize: 13.5, color: "rgba(245,245,243,.7)", lineHeight: 1.6 }}>
                  No report was saved for this attempt.
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
            )}
          </div>
        </div>
      </div>
      <style jsx global>{`
        @keyframes ev-indeterminate-progress {
          from { transform: translateX(-110%); }
          to { transform: translateX(300%); }
        }
        .ev-indeterminate { animation: ev-indeterminate-progress 1.4s ease-in-out infinite; }
      `}</style>
    </AppShell>
  );
}

const headerBar: React.CSSProperties = { display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 28px", height: 60, borderBottom: "1px solid rgba(255,255,255,.09)" };
const btnPrimary: React.CSSProperties = { fontFamily: "inherit", fontSize: 13.5, fontWeight: 600, color: "#0a0a0b", background: "#fff", border: "none", padding: "10px 18px", borderRadius: 9, cursor: "pointer" };
const btnGhost: React.CSSProperties = { fontFamily: "inherit", fontSize: 13.5, fontWeight: 500, color: "#f5f5f3", background: "transparent", border: "1px solid rgba(255,255,255,.2)", padding: "10px 18px", borderRadius: 9, cursor: "pointer" };
