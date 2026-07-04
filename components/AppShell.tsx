"use client";

import { useState } from "react";
import AppSidebar, { type SidebarKey } from "./AppSidebar";
import SettingsModal from "./SettingsModal";

interface AppShellProps {
  active: SidebarKey;
  theme?: "light" | "dark";
  /** background for the main column (defaults to shell) */
  background?: string;
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
  children,
}: AppShellProps) {
  const [settingsOpen, setSettingsOpen] = useState(false);

  return (
    <div style={{ minHeight: "100vh", display: "flex", background }}>
      <AppSidebar
        theme={theme}
        active={active}
        onSettings={() => setSettingsOpen(true)}
      />
      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
        {children}
      </div>
      <SettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
  );
}
