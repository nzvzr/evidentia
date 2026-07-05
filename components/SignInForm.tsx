"use client";

import { useState } from "react";

interface SignInFormProps {
  onSubmit: (email: string, password: string) => void;
  onSwitch: () => void;
}

export default function SignInForm({ onSubmit, onSwitch }: SignInFormProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit(email, password);
      }}
    >
      <h2 style={{ fontSize: 22, fontWeight: 700, letterSpacing: "-.02em", margin: 0 }}>
        Sign in
      </h2>
      <div style={{ fontSize: 13.5, color: "var(--sub)", marginTop: 6 }}>
        Welcome back. Enter your details to continue.
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 14, marginTop: 22 }}>
        <label>
          <div style={labelStyle}>Email</div>
          <input
            type="email"
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
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
            style={inputStyle}
          />
        </label>
      </div>
      <button type="submit" style={submitBtn}>
        Continue
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
