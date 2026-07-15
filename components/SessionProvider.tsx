"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { purgeAuthenticatedCache, purgeLegacyAuthenticatedData } from "@/lib/sessionCache";
import type { Membership, SessionUser } from "@/lib/types";

/**
 * Client-side session state.
 *
 * There is no token here, and none in localStorage: the session lives in
 * httpOnly cookies that JavaScript cannot read. This context only holds the
 * *identity* the server reports via /api/auth/me, so the UI can render the right
 * thing. Authorization is always re-checked server-side on every request.
 */

interface SessionState {
  user: SessionUser | null;
  companies: Membership[];
  /** The active organization (first membership) — drives tenant-scoped views. */
  activeCompany: Membership | null;
  status: "loading" | "authenticated" | "anonymous";
  isAuthenticated: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (input: SignUpInput) => Promise<void>;
  signOut: () => Promise<void>;
  refresh: () => Promise<void>;
}

export interface SignUpInput {
  name: string;
  email: string;
  company: string;
  password: string;
}

const SessionContext = createContext<SessionState | null>(null);

async function readError(res: Response, fallback: string): Promise<string> {
  const data = await res.json().catch(() => ({}));
  return typeof data?.error === "string" ? data.error : fallback;
}

export default function SessionProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<SessionUser | null>(null);
  const [companies, setCompanies] = useState<Membership[]>([]);
  const [status, setStatus] = useState<SessionState["status"]>("loading");

  const refresh = useCallback(async () => {
    try {
      const res = await fetch("/api/auth/me", { cache: "no-store" });
      if (!res.ok) {
        // Session gone (expired/revoked): treat it as a session change.
        purgeAuthenticatedCache();
        setUser(null);
        setCompanies([]);
        setStatus("anonymous");
        return;
      }
      const data = await res.json();
      setUser(data.user ?? null);
      setCompanies(data.companies ?? []);
      setStatus(data.user ? "authenticated" : "anonymous");
    } catch {
      setUser(null);
      setCompanies([]);
      setStatus("anonymous");
    }
  }, []);

  useEffect(() => {
    // Migration: delete tenant content that older builds cached globally.
    // Narrow on purpose — this runs on every page load, including mid-flow pages
    // that legitimately read their own transient state.
    purgeLegacyAuthenticatedData();
    void refresh();
  }, [refresh]);

  const signIn = useCallback(
    async (email: string, password: string) => {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      if (!res.ok) throw new Error(await readError(res, "Invalid email or password"));
      // A different account may have used this browser: clear its residue before
      // the new session can read anything.
      purgeAuthenticatedCache();
      const data = await res.json();
      setUser(data.user);
      setCompanies(data.companies ?? []);
      setStatus("authenticated");
    },
    [],
  );

  const signUp = useCallback(async (input: SignUpInput) => {
    const res = await fetch("/api/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
    if (!res.ok) throw new Error(await readError(res, "Registration failed"));
    purgeAuthenticatedCache();
    const data = await res.json();
    setUser(data.user);
    setCompanies(data.companies ?? []);
    setStatus("authenticated");
  }, []);

  const signOut = useCallback(async () => {
    try {
      await fetch("/api/auth/logout", { method: "POST" });
    } finally {
      // Authenticated data must not survive logout in this browser.
      purgeAuthenticatedCache();
      setUser(null);
      setCompanies([]);
      setStatus("anonymous");
    }
  }, []);

  const value = useMemo<SessionState>(
    () => ({
      user,
      companies,
      activeCompany: companies[0] ?? null,
      status,
      isAuthenticated: status === "authenticated",
      signIn,
      signUp,
      signOut,
      refresh,
    }),
    [user, companies, status, signIn, signUp, signOut, refresh],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionState {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used inside a SessionProvider");
  return ctx;
}
