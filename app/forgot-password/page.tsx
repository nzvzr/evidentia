"use client";

import Link from "next/link";
import { useState } from "react";
import AuthCard from "@/components/AuthCard";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await fetch("/api/auth/password-reset", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
    } finally {
      setBusy(false);
      // Always report success: whether the address is registered is not
      // disclosed here, matching the backend's non-enumerating response.
      setSent(true);
    }
  };

  return (
    <AuthCard>
      {sent ? (
        <>
          <h2 style={heading}>Check your email</h2>
          <p style={body}>
            If an account exists for <strong>{email}</strong>, we&apos;ve sent a link to reset
            your password. It expires in one hour and can be used once.
          </p>
          <Link href="/login" style={backLink}>
            Back to sign in
          </Link>
        </>
      ) : (
        <form onSubmit={submit}>
          <h2 style={heading}>Reset your password</h2>
          <p style={body}>
            Enter your email and we&apos;ll send you a link to choose a new password.
          </p>
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
          <button type="submit" disabled={busy} style={{ ...submitBtn, opacity: busy ? 0.6 : 1 }}>
            {busy ? "Sending…" : "Send reset link"}
          </button>
          <div style={{ textAlign: "center", marginTop: 16 }}>
            <Link href="/login" style={{ fontSize: 13, color: "var(--sub)" }}>
              Back to sign in
            </Link>
          </div>
        </form>
      )}
    </AuthCard>
  );
}

const heading: React.CSSProperties = {
  fontSize: 22,
  fontWeight: 700,
  letterSpacing: "-.02em",
  margin: 0,
};

const body: React.CSSProperties = {
  fontSize: 13.5,
  color: "var(--sub)",
  marginTop: 8,
  marginBottom: 20,
  lineHeight: 1.55,
};

const labelStyle: React.CSSProperties = { fontSize: 12, color: "var(--sub)", marginBottom: 6 };

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

const backLink: React.CSSProperties = {
  display: "inline-block",
  marginTop: 8,
  fontSize: 13,
  fontWeight: 600,
  color: "var(--accent)",
};
