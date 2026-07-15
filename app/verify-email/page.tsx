"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import AuthCard from "@/components/AuthCard";
import { useSession } from "@/components/SessionProvider";

type State = "verifying" | "ok" | "failed" | "missing";

function VerifyInner() {
  const token = useSearchParams().get("token") ?? "";
  const { refresh } = useSession();
  const [state, setState] = useState<State>(token ? "verifying" : "missing");
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (!token) return;
    let cancelled = false;

    (async () => {
      try {
        const res = await fetch("/api/auth/verify-email", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token }),
        });
        if (cancelled) return;
        if (res.ok) {
          setState("ok");
          // Pick up the new emailVerified flag.
          await refresh();
        } else {
          const data = await res.json().catch(() => ({}));
          setMessage(typeof data?.error === "string" ? data.error : "");
          setState("failed");
        }
      } catch {
        if (!cancelled) setState("failed");
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [token, refresh]);

  if (state === "missing") {
    return (
      <AuthCard>
        <h2 style={heading}>Invalid link</h2>
        <p style={body}>This verification link is missing its token.</p>
      </AuthCard>
    );
  }

  if (state === "verifying") {
    return (
      <AuthCard>
        <h2 style={heading}>Verifying…</h2>
        <p style={body}>Confirming your email address.</p>
      </AuthCard>
    );
  }

  if (state === "ok") {
    return (
      <AuthCard>
        <h2 style={heading}>Email verified</h2>
        <p style={body}>Your address is confirmed. You&apos;re all set.</p>
        <Link href="/workspace" style={link}>
          Go to workspace
        </Link>
      </AuthCard>
    );
  }

  return (
    <AuthCard>
      <h2 style={heading}>Verification failed</h2>
      <p style={body}>
        {message || "This link is invalid or has expired. Verification links are single-use."}
      </p>
      <Link href="/workspace" style={link}>
        Continue to workspace
      </Link>
    </AuthCard>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense fallback={null}>
      <VerifyInner />
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

const link: React.CSSProperties = {
  display: "inline-block",
  marginTop: 18,
  fontSize: 13,
  fontWeight: 600,
  color: "var(--accent)",
};
