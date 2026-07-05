"use client";

import { useEffect, useState } from "react";
import { MARKETS } from "@/lib/markets";
import { PERSONAS } from "@/lib/personas";
import { useSettings } from "@/lib/useSettings";
import type { AppSettings } from "@/lib/types";

interface SettingsModalProps {
  open: boolean;
  onClose: () => void;
}

export default function SettingsModal({ open, onClose }: SettingsModalProps) {
  const { settings, save } = useSettings();
  const [draft, setDraft] = useState<AppSettings>(settings);

  useEffect(() => {
    if (open) setDraft(settings);
  }, [open, settings]);

  if (!open) return null;

  const set = <K extends keyof AppSettings>(k: K, v: AppSettings[K]) =>
    setDraft((d) => ({ ...d, [k]: v }));

  return (
    <div
      className="no-print"
      onClick={onClose}
      style={overlay}
      role="dialog"
      aria-modal="true"
    >
      <div onClick={(e) => e.stopPropagation()} style={{ ...card, width: 452 }}>
        <h2 style={{ fontSize: 20, fontWeight: 700, letterSpacing: "-.02em", margin: "0 0 20px" }}>
          Settings
        </h2>
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <Field label="Workspace name">
            <input
              value={draft.workspaceName}
              onChange={(e) => set("workspaceName", e.target.value)}
              style={inputStyle}
            />
          </Field>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
            <Field label="Default market">
              <select
                value={draft.defaultMarket}
                onChange={(e) => set("defaultMarket", e.target.value)}
                style={{ ...inputStyle, background: "#fff" }}
              >
                {MARKETS.map((m) => (
                  <option key={m}>{m}</option>
                ))}
              </select>
            </Field>
            <Field label="Default persona">
              <select
                value={draft.defaultPersona}
                onChange={(e) => set("defaultPersona", e.target.value)}
                style={{ ...inputStyle, background: "#fff" }}
              >
                {PERSONAS.map((p) => (
                  <option key={p.id}>{p.title}</option>
                ))}
              </select>
            </Field>
          </div>
          <Field label="Export format">
            <SegmentGroup
              options={["US Letter", "A4"]}
              value={draft.exportFormat}
              onChange={(v) => set("exportFormat", v as AppSettings["exportFormat"])}
            />
          </Field>
          <Field label="Theme">
            <SegmentGroup
              options={["System", "Light", "Dark"]}
              value={draft.theme}
              onChange={(v) => set("theme", v as AppSettings["theme"])}
            />
          </Field>
        </div>
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 24 }}>
          <button onClick={onClose} style={secondaryBtn}>
            Cancel
          </button>
          <button
            onClick={() => {
              save(draft);
              onClose();
            }}
            style={primaryBtn}
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={{ fontSize: 12, color: "var(--sub)", marginBottom: 6 }}>{label}</div>
      {children}
    </div>
  );
}

function SegmentGroup({
  options,
  value,
  onChange,
}: {
  options: string[];
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div style={{ display: "flex", gap: 8 }}>
      {options.map((o) => {
        const on = o === value;
        return (
          <button
            key={o}
            onClick={() => onChange(o)}
            style={{
              flex: 1,
              textAlign: "center",
              fontSize: 13,
              fontWeight: on ? 600 : 500,
              color: on ? "#fff" : "var(--ink)",
              background: on ? "#0a0a0b" : "#fff",
              border: on ? "none" : "1px solid var(--line2)",
              padding: 9,
              borderRadius: 8,
              cursor: "pointer",
              fontFamily: "inherit",
            }}
          >
            {o}
          </button>
        );
      })}
    </div>
  );
}

const overlay: React.CSSProperties = {
  position: "fixed",
  inset: 0,
  zIndex: 100,
  background: "rgba(10,10,11,.55)",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  padding: 24,
};

const card: React.CSSProperties = {
  maxWidth: "100%",
  background: "#fff",
  borderRadius: 14,
  padding: "30px 30px",
  boxShadow: "0 24px 70px rgba(0,0,0,.35)",
};

const inputStyle: React.CSSProperties = {
  width: "100%",
  fontFamily: "inherit",
  fontSize: 14,
  padding: "10px 12px",
  border: "1px solid var(--line2)",
  borderRadius: 9,
  outline: "none",
  boxSizing: "border-box",
};

const primaryBtn: React.CSSProperties = {
  fontFamily: "inherit",
  fontSize: 13.5,
  fontWeight: 600,
  color: "#fff",
  background: "#0a0a0b",
  border: "none",
  padding: "10px 20px",
  borderRadius: 9,
  cursor: "pointer",
};

const secondaryBtn: React.CSSProperties = {
  fontFamily: "inherit",
  fontSize: 13.5,
  fontWeight: 500,
  color: "var(--ink)",
  background: "#fff",
  border: "1px solid var(--line2)",
  padding: "10px 18px",
  borderRadius: 9,
  cursor: "pointer",
};
