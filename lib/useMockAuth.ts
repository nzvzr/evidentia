"use client";

import { useCallback, useEffect, useState } from "react";
import type { MockUser } from "./types";

const STORAGE_KEY = "evidentia:user";

function readUser(): MockUser | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as MockUser) : null;
  } catch {
    return null;
  }
}

export interface UseMockAuth {
  user: MockUser | null;
  isAuthenticated: boolean;
  signIn: (email: string, _password?: string) => MockUser;
  signUp: (
    name: string,
    email: string,
    company: string,
    _password?: string,
  ) => MockUser;
  signOut: () => void;
}

/**
 * Visual-only mock auth. Persists a fake user in localStorage.
 * There is no real authentication and it never blocks the demo flow.
 */
export function useMockAuth(): UseMockAuth {
  const [user, setUser] = useState<MockUser | null>(null);

  useEffect(() => {
    setUser(readUser());
    const onStorage = (e: StorageEvent) => {
      if (e.key === STORAGE_KEY) setUser(readUser());
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const persist = useCallback((next: MockUser) => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {
      /* ignore */
    }
    setUser(next);
  }, []);

  const signIn = useCallback(
    (email: string) => {
      const derivedName = email.split("@")[0] || "Member";
      const next: MockUser = {
        name: derivedName.charAt(0).toUpperCase() + derivedName.slice(1),
        email: email || "demo@evidentia.app",
        company: "Northreach Cloud",
      };
      persist(next);
      return next;
    },
    [persist],
  );

  const signUp = useCallback(
    (name: string, email: string, company: string) => {
      const next: MockUser = {
        name: name || "Alex Rivera",
        email: email || "demo@evidentia.app",
        company: company || "Northreach Cloud",
      };
      persist(next);
      return next;
    },
    [persist],
  );

  const signOut = useCallback(() => {
    try {
      window.localStorage.removeItem(STORAGE_KEY);
    } catch {
      /* ignore */
    }
    setUser(null);
  }, []);

  return {
    user,
    isAuthenticated: !!user,
    signIn,
    signUp,
    signOut,
  };
}
