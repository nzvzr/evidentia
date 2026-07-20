"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import Logo from "./Logo";
import { useSession } from "./SessionProvider";
import { fetchBackendReports } from "@/lib/reportsApi";
import type { EvidentiaReport } from "@/lib/types";

export type SidebarKey = "workspace" | "reports" | "playbooks" | "documents";

interface AppSidebarProps {
  theme?: "light" | "dark";
  active?: SidebarKey;
  onSettings?: () => void;
}

interface Palette {
  bg: string;
  border: string;
  text: string;
  sub: string;
  tile: string;
  activeBg: string;
  activeText: string;
}

const LIGHT: Palette = {
  bg: "#ffffff",
  border: "rgba(15,15,20,.09)",
  text: "#0b0b0c",
  sub: "#77777c",
  tile: "#f1f1ee",
  activeBg: "rgba(47,86,224,.09)",
  activeText: "#2f56e0",
};

const DARK: Palette = {
  bg: "#0d0d0f",
  border: "rgba(255,255,255,.08)",
  text: "#f4f4f2",
  sub: "rgba(244,244,242,.5)",
  tile: "rgba(255,255,255,.08)",
  activeBg: "rgba(47,86,224,.18)",
  activeText: "#ffffff",
};

const NAV: { key: SidebarKey; label: string; letter: string; href: string }[] = [
  { key: "workspace", label: "Workspace", letter: "W", href: "/workspace" },
  { key: "reports", label: "Reports", letter: "R", href: "/reports" },
  { key: "playbooks", label: "Playbooks", letter: "P", href: "/playbooks" },
  { key: "documents", label: "Documents", letter: "D", href: "/documents" },
];

export default function AppSidebar({
  theme = "light",
  active = "workspace",
  onSettings,
}: AppSidebarProps) {
  const router = useRouter();
  const pal = theme === "dark" ? DARK : LIGHT;
  const { status, activeCompany } = useSession();
  const reportScope = status === "authenticated" ? activeCompany?.id ?? null : null;
  const [recentState, setRecentState] = useState<{
    scope: string | null;
    reports: EvidentiaReport[];
  }>({ scope: null, reports: [] });
  const recentReports = recentState.scope === reportScope ? recentState.reports : [];

  useEffect(() => {
    if (!reportScope) return;
    let cancelled = false;
    void fetchBackendReports().then((reports) => {
      if (!cancelled) setRecentState({ scope: reportScope, reports: reports.slice(0, 3) });
    });
    return () => {
      cancelled = true;
    };
  }, [reportScope]);

  return (
    <aside
      className="no-print"
      style={{
        width: 244,
        flex: "none",
        height: "100vh",
        position: "sticky",
        top: 0,
        boxSizing: "border-box",
        background: pal.bg,
        borderRight: `1px solid ${pal.border}`,
        display: "flex",
        flexDirection: "column",
        padding: "18px 14px",
      }}
    >
      <button
        onClick={() => router.push("/")}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "6px 8px",
          background: "transparent",
          border: "none",
          cursor: "pointer",
          font: "inherit",
        }}
        aria-label="Go to landing page"
      >
        <Logo size={26} showWordmark wordmarkColor={pal.text} />
      </button>

      <button
        onClick={() => router.push("/workspace")}
        style={{
          margin: "18px 0 6px",
          fontFamily: "inherit",
          fontSize: 13,
          fontWeight: 600,
          display: "flex",
          alignItems: "center",
          gap: 9,
          color: pal.text,
          background: pal.tile,
          border: `1px solid ${pal.border}`,
          borderRadius: 9,
          padding: "10px 13px",
          cursor: "pointer",
        }}
      >
        <span style={{ fontSize: 15, lineHeight: 1, fontWeight: 400 }}>+</span>
        New workspace
      </button>

      <div style={sectionLabel(pal)}>NAVIGATE</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        {NAV.map((n) => {
          const on = n.key === active;
          return (
            <button
              key={n.key}
              onClick={() => router.push(n.href)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 11,
                padding: "8px 10px",
                borderRadius: 8,
                cursor: "pointer",
                background: on ? pal.activeBg : "transparent",
                border: "none",
                font: "inherit",
                textAlign: "left",
              }}
            >
              <span
                style={{
                  width: 22,
                  height: 22,
                  flex: "none",
                  borderRadius: 6,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontFamily: "var(--font-plex-mono), monospace",
                  fontSize: 10.5,
                  fontWeight: 600,
                  background: on ? "#2f56e0" : pal.tile,
                  color: on ? "#fff" : pal.sub,
                }}
              >
                {n.letter}
              </span>
              <span
                style={{
                  fontSize: 13.5,
                  fontWeight: on ? 600 : 500,
                  color: on ? pal.activeText : pal.text,
                }}
              >
                {n.label}
              </span>
            </button>
          );
        })}
      </div>

      <div style={sectionLabel(pal)}>RECENT</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
        {recentReports.map((report) => (
          <button
            key={report.id}
            onClick={() => router.push(`/reports/${report.id}`)}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              padding: "7px 10px",
              borderRadius: 7,
              cursor: "pointer",
              background: "transparent",
              border: "none",
              font: "inherit",
              textAlign: "left",
            }}
          >
            <span
              style={{
                width: 5,
                height: 5,
                borderRadius: "50%",
                flex: "none",
                background: pal.sub,
              }}
            />
            <span
              style={{
                fontSize: 12.5,
                color: pal.sub,
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
              }}
            >
              {report.persona} · {report.market}
            </span>
          </button>
        ))}
        {status === "authenticated" && recentReports.length === 0 && (
          <div style={{ padding: "7px 10px", fontSize: 12, color: pal.sub }}>
            No reports yet
          </div>
        )}
      </div>

      <div style={{ flex: 1, minHeight: 20 }} />

      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 1,
          paddingTop: 12,
          borderTop: `1px solid ${pal.border}`,
        }}
      >
        {[
          { label: "Settings", letter: "S", onClick: onSettings },
          { label: "Help", letter: "?", onClick: undefined },
        ].map((b) => (
          <button
            key={b.label}
            onClick={b.onClick}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 11,
              padding: "8px 10px",
              borderRadius: 8,
              cursor: "pointer",
              background: "transparent",
              border: "none",
              font: "inherit",
              textAlign: "left",
            }}
          >
            <span
              style={{
                width: 22,
                height: 22,
                flex: "none",
                borderRadius: 6,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontFamily: "var(--font-plex-mono), monospace",
                fontSize: 10.5,
                fontWeight: 600,
                background: pal.tile,
                color: pal.sub,
              }}
            >
              {b.letter}
            </span>
            <span style={{ fontSize: 13.5, fontWeight: 500, color: pal.text }}>
              {b.label}
            </span>
          </button>
        ))}

        <AccountCard pal={pal} />
      </div>
    </aside>
  );
}

/** The signed-in user, their organization + role, and sign out. */
function AccountCard({ pal }: { pal: Palette }) {
  const router = useRouter();
  const { user, activeCompany, signOut } = useSession();

  if (!user) return null;

  const initial = (user.name || user.email).charAt(0).toUpperCase();

  const handleSignOut = async () => {
    await signOut();
    router.push("/login");
    router.refresh();
  };

  return (
    <div style={{ marginTop: 8, paddingTop: 10, borderTop: `1px solid ${pal.border}` }}>
      <div style={{ display: "flex", alignItems: "center", gap: 11, padding: "6px 10px" }}>
        <span
          style={{
            width: 22,
            height: 22,
            flex: "none",
            borderRadius: 6,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontFamily: "var(--font-plex-mono), monospace",
            fontSize: 10.5,
            fontWeight: 600,
            background: pal.tile,
            color: pal.text,
          }}
        >
          {initial}
        </span>
        <span style={{ minWidth: 0 }}>
          <span
            style={{
              display: "block",
              fontSize: 12.5,
              fontWeight: 600,
              color: pal.text,
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
          >
            {user.name || user.email}
          </span>
          {activeCompany && (
            <span
              style={{
                display: "block",
                fontSize: 11,
                color: pal.sub,
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
              }}
            >
              {activeCompany.name} · {activeCompany.role}
            </span>
          )}
        </span>
      </div>
      <button
        onClick={handleSignOut}
        style={{
          display: "block",
          width: "100%",
          padding: "7px 10px",
          marginTop: 2,
          borderRadius: 8,
          cursor: "pointer",
          background: "transparent",
          border: "none",
          font: "inherit",
          fontSize: 12.5,
          color: pal.sub,
          textAlign: "left",
        }}
      >
        Sign out
      </button>
    </div>
  );
}

function sectionLabel(pal: Palette): React.CSSProperties {
  return {
    fontFamily: "var(--font-plex-mono), monospace",
    fontSize: 9.5,
    color: pal.sub,
    letterSpacing: ".12em",
    padding: "0 10px",
    margin: "20px 0 9px",
  };
}
