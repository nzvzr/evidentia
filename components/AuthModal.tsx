"use client";

import { useEffect, useState } from "react";
import Logo from "./Logo";
import { useSession } from "./SessionProvider";
import SignInForm from "./SignInForm";
import SignUpForm from "./SignUpForm";

interface AuthModalProps {
  open: boolean;
  onClose: () => void;
  /** called after a successful sign in / sign up */
  onSuccess?: () => void;
  initialMode?: "signin" | "signup";
}

/**
 * Real authentication. `signIn`/`signUp` hit the server and throw on failure;
 * the forms surface the error and the modal only closes on success.
 */
export default function AuthModal({
  open,
  onClose,
  onSuccess,
  initialMode = "signin",
}: AuthModalProps) {
  const { signIn, signUp } = useSession();
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
            onSubmit={async (email, password) => {
              await signIn(email, password);
              finish();
            }}
            onSwitch={() => setMode("signup")}
          />
        ) : (
          <SignUpForm
            onSubmit={async (input) => {
              await signUp(input);
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
