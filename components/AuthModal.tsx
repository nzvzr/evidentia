"use client";

import { useEffect, useState } from "react";
import Logo from "./Logo";
import SignInForm from "./SignInForm";
import SignUpForm from "./SignUpForm";
import { useMockAuth } from "@/lib/useMockAuth";

interface AuthModalProps {
  open: boolean;
  onClose: () => void;
  /** called after a successful mock sign in / sign up */
  onSuccess?: () => void;
  initialMode?: "signin" | "signup";
}

export default function AuthModal({
  open,
  onClose,
  onSuccess,
  initialMode = "signin",
}: AuthModalProps) {
  const { signIn, signUp } = useMockAuth();
  const [mode, setMode] = useState<"signin" | "signup">(initialMode);

  useEffect(() => {
    if (open) setMode(initialMode);
  }, [open, initialMode]);

  if (!open) return null;

  const finish = () => {
    onClose();
    onSuccess?.();
  };

  return (
    <div
      className="no-print"
      onClick={onClose}
      style={overlay}
      role="dialog"
      aria-modal="true"
    >
      <div onClick={(e) => e.stopPropagation()} style={card}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 22 }}>
          <Logo size={28} showWordmark />
        </div>
        {mode === "signin" ? (
          <SignInForm
            onSubmit={(email, password) => {
              signIn(email, password);
              finish();
            }}
            onSwitch={() => setMode("signup")}
          />
        ) : (
          <SignUpForm
            onSubmit={(name, email, company, password) => {
              signUp(name, email, company, password);
              finish();
            }}
            onSwitch={() => setMode("signin")}
          />
        )}
      </div>
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
  width: 404,
  maxWidth: "100%",
  background: "#fff",
  borderRadius: 14,
  padding: "34px 32px",
  boxShadow: "0 24px 70px rgba(0,0,0,.35)",
  color: "var(--ink)",
};
