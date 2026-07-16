"""Request body size cap.

Implemented as raw ASGI rather than a `BaseHTTPMiddleware` so it can reject the
request *before* the body is buffered or parsed:

1. A declared `Content-Length` over the cap is refused immediately — we never
   read the payload at all.
2. A chunked / undeclared body is counted as it streams, and aborted the moment
   it crosses the cap. Without this, `Transfer-Encoding: chunked` would bypass a
   Content-Length-only check.

Returns 413 with the same machine-readable-code shape as the other errors.
"""

from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

PAYLOAD_TOO_LARGE_CODE = "payload_too_large"


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int | None = None) -> None:
        self.app = app
        self._max_bytes = max_bytes

    # Routes that legitimately carry a file need a larger cap than the JSON
    # API. The raised cap covers exactly the multipart upload endpoints; the
    # per-FILE byte limit is still enforced while the upload handler streams
    # the part (bytes are counted here too, so Content-Length is never the
    # only guard on either path).
    _UPLOAD_PATH_PREFIX = "/api/documents"
    _UPLOAD_PATH_SUFFIXES = ("/upload", "/versions")
    _MULTIPART_OVERHEAD = 64 * 1024

    @property
    def max_bytes(self) -> int:
        if self._max_bytes is not None:
            return self._max_bytes
        from app.core.config import get_settings

        return get_settings().evidentia_max_body_bytes

    def _limit_for(self, scope: Scope) -> int:
        if self._max_bytes is not None:
            return self._max_bytes
        path = scope.get("path", "")
        if path.startswith(self._UPLOAD_PATH_PREFIX) and path.endswith(self._UPLOAD_PATH_SUFFIXES):
            from app.core.config import get_settings

            settings = get_settings()
            return max(
                settings.evidentia_max_body_bytes,
                settings.evidentia_upload_max_file_bytes + self._MULTIPART_OVERHEAD,
            )
        return self.max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limit = self._limit_for(scope)

        # 1. Declared oversize: refuse without reading the body.
        for key, value in scope.get("headers", []):
            if key == b"content-length":
                try:
                    if int(value) > limit:
                        await self._reject(scope, send)
                        return
                except ValueError:
                    await self._reject(scope, send)
                    return

        # 2. Undeclared / chunked: count bytes as they arrive.
        received = 0
        exceeded = False

        async def counting_receive() -> Message:
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    exceeded = True
                    # Stop the stream; the handler sees a truncated body and the
                    # 413 below is what actually reaches the client.
                    return {"type": "http.disconnect"}
            return message

        sent_response = False

        async def guarded_send(message: Message) -> None:
            nonlocal sent_response
            if exceeded and not sent_response:
                sent_response = True
                await self._reject(scope, send)
                return
            if exceeded:
                return
            sent_response = True
            await send(message)

        await self.app(scope, counting_receive, guarded_send)

        if exceeded and not sent_response:
            await self._reject(scope, send)

    async def _reject(self, scope: Scope, send: Send) -> None:
        response = JSONResponse(
            status_code=413,
            content={"code": PAYLOAD_TOO_LARGE_CODE, "detail": "Request body too large."},
        )
        await response(scope, _noop_receive, send)


async def _noop_receive() -> Message:
    """A Response never pulls from receive; this satisfies the ASGI signature."""
    return {"type": "http.disconnect"}
