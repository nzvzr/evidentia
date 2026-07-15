"use client";

import { useState } from "react";
import type { SignUpInput } from "./SessionProvider";

interface SignUpFormProps {
  onSubmit: (input: SignUpInput) => Promise<void>;
  onSwitch: () => void;
}

/** Mirrors the backend's MIN_PASSWORD_LENGTH so the user gets instant feedback;
 *  the backend re-validates regardless. */
const MIN_PASSWORD_LENGTH = 12;

export default function SignUpForm({ onSubmit, onSwitch }: SignUpFormProps) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [company, setCompany] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const tooShort = password.length > 0 && password.length < MIN_PASSWORD_LENGTH;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (password.length < MIN_PASSWORD_LENGTH) {
      setError(`Password must be at least ${MIN_PASSWORD_LENGTH} characters`);
      return;
    }
    setBusy(true);
    try {
      await onSubmit({ name, email, company, password });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Registration failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit}>
      <h2 style={{ fontSize: 22, fontWeight: 700, letterSpacing: "-.02em", margin: 0 }}>
        Create your account
      </h2>
      <div style={{ fontSize: 13.5, color: "var(--sub)", marginTop: 6 }}>
        Start turning documentation into playbooks.
      </div>

      {error && (
        <div role="alert" style={errorStyle}>
          {error}
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 13, marginTop: 22 }}>
        <label>
          <div style={labelStyle}>Name</div>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoComplete="name"
            placeholder="Alex Rivera"
            style={inputStyle}
          />
        </label>
        <label>
          <div style={labelStyle}>Work email</div>
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
          <div style={labelStyle}>Organization</div>
          <input
            value={company}
            onChange={(e) => setCompany(e.target.value)}
            autoComplete="organization"
            placeholder="Your company"
            style={inputStyle}
          />
          <div style={hintStyle}>
            You&apos;ll be the owner. Your documents and reports stay private to it.
          </div>
        </label>
        <label>
          <div style={labelStyle}>Password</div>
          <input
            type="password"
            required
            autoComplete="new-password"
            minLength={MIN_PASSWORD_LENGTH}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••••••"
            style={{
              ...inputStyle,
              borderColor: tooShort ? "#e0a9a9" : "var(--line2)",
            }}
          />
          <div style={hintStyle}>At least {MIN_PASSWORD_LENGTH} characters.</div>
        </label>
      </div>

      <button type="submit" disabled={busy} style={{ ...submitBtn, opacity: busy ? 0.6 : 1 }}>
        {busy ? "Creating account…" : "Create account"}
      </button>

      <div style={{ textAlign: "center", marginTop: 16, fontSize: 13, color: "var(--sub)" }}>
        Have an account?{" "}
        <button type="button" onClick={onSwitch} style={linkBtn}>
          Sign in
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

const hintStyle: React.CSSProperties = {
  fontSize: 11.5,
  color: "var(--sub)",
  marginTop: 5,
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
  marginTop: 20,
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
