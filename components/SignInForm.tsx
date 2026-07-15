"use client";

import Link from "next/link";
import { useState } from "react";

interface SignInFormProps {
  onSubmit: (email: string, password: string) => Promise<void>;
  onSwitch: () => void;
}

export default function SignInForm({ onSubmit, onSwitch }: SignInFormProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await onSubmit(email, password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign in failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit}>
      <h2 style={{ fontSize: 22, fontWeight: 700, letterSpacing: "-.02em", margin: 0 }}>
        Sign in
      </h2>
      <div style={{ fontSize: 13.5, color: "var(--sub)", marginTop: 6 }}>
        Welcome back. Enter your details to continue.
      </div>

      {error && (
        <div role="alert" style={errorStyle}>
          {error}
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 14, marginTop: 22 }}>
        <label>
          <div style={labelStyle}>Email</div>
          <input
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@company.com"
            style={inputStyle}
          />
        </label>
        <label>
          <div style={labelStyle}>Password</div>
          <input
            type="password"
            required
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
            style={inputStyle}
          />
        </label>
      </div>

      <div style={{ textAlign: "right", marginTop: 10 }}>
        <Link href="/forgot-password" style={{ fontSize: 12.5, color: "var(--sub)" }}>
          Forgot password?
        </Link>
      </div>

      <button type="submit" disabled={busy} style={{ ...submitBtn, opacity: busy ? 0.6 : 1 }}>
        {busy ? "Signing in…" : "Continue"}
      </button>

      <div style={{ textAlign: "center", marginTop: 16, fontSize: 13, color: "var(--sub)" }}>
        No account?{" "}
        <button type="button" onClick={onSwitch} style={linkBtn}>
          Create one
        </button>
      </div>
    </form>
  );
}

const labelStyle: React.CSSProperties = {
  fontSize: 12,
  color: "var(--sub)",
  marginBottom: 6,
};

const inputStyle: React.CSSProperties = {
  width: "100%",
  fontFamily: "inherit",
  fontSize: 14,
  padding: "11px 13px",
  border: "1px solid var(--line2)",
  borderRadius: 9,
  outline: "none",
  boxSizing: "border-box",
};

const errorStyle: React.CSSProperties = {
  marginTop: 16,
  padding: "10px 12px",
  fontSize: 13,
  color: "#8a1c1c",
  background: "#fdf1f1",
  border: "1px solid #f2caca",
  borderRadius: 8,
};

const submitBtn: React.CSSProperties = {
  width: "100%",
  marginTop: 16,
  fontFamily: "inherit",
  fontSize: 14,
  fontWeight: 600,
  color: "#fff",
  background: "#0a0a0b",
  border: "none",
  padding: 13,
  borderRadius: 9,
  cursor: "pointer",
};

const linkBtn: React.CSSProperties = {
  fontFamily: "inherit",
  fontSize: 13,
  fontWeight: 600,
  color: "var(--accent)",
  background: "none",
  border: "none",
  cursor: "pointer",
  padding: 0,
};
