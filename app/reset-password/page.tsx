"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import AuthCard from "@/components/AuthCard";

const MIN_PASSWORD_LENGTH = 12;

function ResetInner() {
  const router = useRouter();
  const token = useSearchParams().get("token") ?? "";

  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (password.length < MIN_PASSWORD_LENGTH) {
      setError(`Password must be at least ${MIN_PASSWORD_LENGTH} characters`);
      return;
    }
    if (password !== confirm) {
      setError("Passwords do not match");
      return;
    }

    setBusy(true);
    try {
      const res = await fetch("/api/auth/password-reset", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, password }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setError(typeof data?.error === "string" ? data.error : "This reset link is invalid or expired");
        return;
      }
      setDone(true);
    } catch {
      setError("Could not reach the server. Try again.");
    } finally {
      setBusy(false);
    }
  };

  if (!token) {
    return (
      <AuthCard>
        <h2 style={heading}>Invalid reset link</h2>
        <p style={body}>This link is missing its token. Request a new one.</p>
        <Link href="/forgot-password" style={backLink}>
          Request a new link
        </Link>
      </AuthCard>
    );
  }

  if (done) {
    return (
      <AuthCard>
        <h2 style={heading}>Password updated</h2>
        <p style={body}>
          Your password has been changed and all other sessions were signed out.
        </p>
        <button onClick={() => router.push("/login")} style={submitBtn}>
          Sign in
        </button>
      </AuthCard>
    );
  }

  return (
    <AuthCard>
      <form onSubmit={submit}>
        <h2 style={heading}>Choose a new password</h2>
        <p style={body}>This link can be used once.</p>

        {error && (
          <div role="alert" style={errorStyle}>
            {error}
          </div>
        )}

        <div style={{ display: "flex", flexDirection: "column", gap: 13, marginTop: 18 }}>
          <label>
            <div style={labelStyle}>New password</div>
            <input
              type="password"
              required
              autoComplete="new-password"
              minLength={MIN_PASSWORD_LENGTH}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••••••"
              style={inputStyle}
            />
            <div style={hintStyle}>At least {MIN_PASSWORD_LENGTH} characters.</div>
          </label>
          <label>
            <div style={labelStyle}>Confirm password</div>
            <input
              type="password"
              required
              autoComplete="new-password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              placeholder="••••••••••••"
              style={inputStyle}
            />
          </label>
        </div>

        <button type="submit" disabled={busy} style={{ ...submitBtn, opacity: busy ? 0.6 : 1 }}>
          {busy ? "Updating…" : "Update password"}
        </button>
      </form>
    </AuthCard>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={null}>
      <ResetInner />
    </Suspense>
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
  lineHeight: 1.55,
};

const labelStyle: React.CSSProperties = { fontSize: 12, color: "var(--sub)", marginBottom: 6 };

const hintStyle: React.CSSProperties = { fontSize: 11.5, color: "var(--sub)", marginTop: 5 };

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

const backLink: React.CSSProperties = {
  display: "inline-block",
  marginTop: 16,
  fontSize: 13,
  fontWeight: 600,
  color: "var(--accent)",
};
