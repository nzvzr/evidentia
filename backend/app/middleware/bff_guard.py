"""Refuse requests that did not come through the trusted BFF.

Why this exists
---------------
A backend with `EVIDENTIA_TRUSTED_PROXY_COUNT > 0` *believes* the
`X-Forwarded-For` header it is handed. That is only sound if the header can
genuinely only be written by the trusted proxy. If the backend port is also
reachable from the internet, an attacker connects to it directly, sets their own
`X-Forwarded-For`, and rotates their rate-limit identity at will — which silently
voids every per-IP limit in the system.

The correct fix is network isolation (never expose the backend). This is
defence in depth for when it *is* exposed: with `EVIDENTIA_BFF_SECRET` set, a
request must present the matching `X-Evidentia-BFF` header or be rejected before
it reaches any handler.

Startup refuses the combination "trusting a proxy" + "no BFF secret" in
production (see main.py) — trusting a header you cannot attribute is not a
configuration we allow to ship.
"""

from __future__ import annotations

import hmac

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

# Paths reachable without the BFF secret (liveness probes must work).
_EXEMPT_PATHS = {"/health"}


class BFFGuardMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        from app.core.config import get_settings

        settings = get_settings()
        secret = (settings.evidentia_bff_secret or "").strip()

        if not secret or scope.get("path") in _EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return

        presented = ""
        for key, value in scope.get("headers", []):
            if key == b"x-evidentia-bff":
                presented = value.decode("latin-1")
                break

        # Constant-time compare so the secret cannot be recovered byte by byte.
        if not hmac.compare_digest(presented, secret):
            response = JSONResponse(
                status_code=403,
                content={"code": "direct_access_denied", "detail": "Forbidden."},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
