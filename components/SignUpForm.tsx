"use client";

import { useState } from "react";

interface SignUpFormProps {
  onSubmit: (name: string, email: string, company: string, password: string) => void;
  onSwitch: () => void;
}

export default function SignUpForm({ onSubmit, onSwitch }: SignUpFormProps) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [company, setCompany] = useState("");
  const [password, setPassword] = useState("");

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit(name, email, company, password);
      }}
    >
      <h2 style={{ fontSize: 22, fontWeight: 700, letterSpacing: "-.02em", margin: 0 }}>
        Create your account
      </h2>
      <div style={{ fontSize: 13.5, color: "var(--sub)", marginTop: 6 }}>
        Start turning documentation into playbooks.
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 13, marginTop: 22 }}>
        <label>
          <div style={labelStyle}>Name</div>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Alex Rivera" style={inputStyle} />
        </label>
        <label>
          <div style={labelStyle}>Work email</div>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@company.com"
            style={inputStyle}
          />
        </label>
        <label>
          <div style={labelStyle}>Company</div>
          <input
            value={company}
            onChange={(e) => setCompany(e.target.value)}
            placeholder="Northreach Cloud"
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
        Create account
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
