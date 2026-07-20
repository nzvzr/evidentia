"use client";

import { useState } from "react";
import AppSidebar, { type SidebarKey } from "./AppSidebar";
import SettingsModal from "./SettingsModal";

interface AppShellProps {
  active: SidebarKey;
  theme?: "light" | "dark";
  /** background for the main column (defaults to shell) */
  background?: string;
  /** Let a dense detail view use the full viewport below tablet width. */
  compactOnMobile?: boolean;
  children: React.ReactNode;
}

/**
 * Application layout: persistent sidebar + main column.
 * Used on /workspace, /running, /report. Not used inside the printed playbook.
 */
export default function AppShell({
  active,
  theme = "light",
  background = "var(--shell)",
  compactOnMobile = false,
  children,
}: AppShellProps) {
  const [settingsOpen, setSettingsOpen] = useState(false);

  return (
    <div className={compactOnMobile ? "ev-app-shell ev-app-shell-compact-mobile" : "ev-app-shell"} style={{ minHeight: "100vh", display: "flex", background }}>
      <AppSidebar
        theme={theme}
        active={active}
        onSettings={() => setSettingsOpen(true)}
      />
      <div className="ev-app-main" style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
        {children}
      </div>
      <SettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
  );
}
