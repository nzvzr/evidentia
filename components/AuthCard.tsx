"use client";

import Link from "next/link";
import Logo from "./Logo";

/** Shared shell for the standalone auth pages (login, register, reset, verify). */
export default function AuthCard({ children }: { children: React.ReactNode }) {
  return (
    <div style={page}>
      <div style={card}>
        <Link href="/" style={{ display: "inline-flex", marginBottom: 22 }}>
          <Logo size={28} showWordmark />
        </Link>
        {children}
      </div>
    </div>
  );
}

const page: React.CSSProperties = {
  minHeight: "100vh",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  padding: 24,
  background: "var(--shell, #f7f7f8)",
};

const card: React.CSSProperties = {
  width: 404,
  maxWidth: "100%",
  background: "#fff",
  borderRadius: 14,
  padding: "34px 32px",
  boxShadow: "0 18px 50px rgba(0,0,0,.10)",
  color: "var(--ink)",
};
