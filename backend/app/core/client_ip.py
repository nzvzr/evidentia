"""Client IP resolution behind a reverse proxy.

`X-Forwarded-For` is client-writable, so it is only consulted when we have been
told exactly how many proxies sit in front of us
(`EVIDENTIA_TRUSTED_PROXY_COUNT`). The header is a chain:

    X-Forwarded-For: <spoofed...>, <real client>, <proxy1>, ... <proxy N-1>

Each proxy *appends the address it received the connection from*. So with N
trusted proxies, the only entry we can vouch for is the Nth from the right — it
was written by the innermost trusted proxy. Anything to the left of it may have
been injected by the client and is ignored.

With `EVIDENTIA_TRUSTED_PROXY_COUNT=0` (the default) the header is ignored
entirely and the TCP peer address is used, so a direct-to-internet deployment
cannot be spoofed at all.
"""

from __future__ import annotations

import ipaddress
from typing import Optional

from fastapi import Request

from app.core.config import get_settings

UNKNOWN_IP = "unknown"


def _valid_ip(value: str) -> Optional[str]:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def get_client_ip(request: Request) -> str:
    """The caller's IP, trusting only as many proxy hops as we are configured to.

    `X-Real-IP` is deliberately NOT consulted, at any hop count. It is a
    single-value, client-writable header with no chain to validate against, so
    honouring it would let any caller rotate their own rate-limit identity. Only
    the validated `X-Forwarded-For` chain is used.
    """
    peer = request.client.host if request.client else UNKNOWN_IP

    hops = get_settings().evidentia_trusted_proxy_count
    if hops <= 0:
        # Not behind a proxy: XFF is attacker-controlled, ignore it.
        return peer

    forwarded = request.headers.get("x-forwarded-for")
    if not forwarded:
        return peer

    parts = [p.strip() for p in forwarded.split(",") if p.strip()]
    # A chain shorter than the number of proxies we expect means the header did
    # not come through the full trusted path — fall back to the peer.
    if len(parts) < hops:
        return peer

    candidate = _valid_ip(parts[-hops])
    return candidate or peer
