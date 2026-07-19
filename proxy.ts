import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Route protection.
 *
 * This is a *first* gate, not the only one: it checks for the presence of a
 * session cookie so unauthenticated users are sent to /login instead of seeing
 * an empty app shell. It deliberately does not attempt to validate the token —
 * every API route and the backend re-verify the session on each request, which
 * is where authorization actually happens.
 */

const PROTECTED = ["/workspace", "/running", "/reports", "/documents", "/playbooks", "/playbook"];
const AUTH_PAGES = ["/login", "/register"];

const ACCESS_COOKIE = "evidentia_at";
const REFRESH_COOKIE = "evidentia_rt";

export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;

  const hasSession =
    Boolean(request.cookies.get(ACCESS_COOKIE)?.value) ||
    Boolean(request.cookies.get(REFRESH_COOKIE)?.value);

  if (!hasSession && PROTECTED.some((p) => pathname === p || pathname.startsWith(`${p}/`))) {
    const login = new URL("/login", request.url);
    // Preserve where they were headed so login can send them back.
    login.searchParams.set("next", `${pathname}${search}`);
    return NextResponse.redirect(login);
  }

  // Already signed in? Don't show the login/register pages.
  if (hasSession && AUTH_PAGES.includes(pathname)) {
    return NextResponse.redirect(new URL("/workspace", request.url));
  }

  return NextResponse.next();
}

export const config = {
  // Everything except API routes, static assets, and the public landing page.
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)"],
};
