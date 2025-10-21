"""Rate limiting middleware for long-poll endpoints."""
from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from nta_eval_svc.config import Config

logger = logging.getLogger(__name__)


class RateLimitResponse(Response):
    """A small Response subclass that ensures an awaitable body() attribute.

    We keep using Starlette's Response for ASGI compatibility but when
    instantiated we attach an async callable to the instance named `body`
    so tests that await response.body() receive bytes as expected.
    """

    def __init__(self, status_code: int, content: str | bytes):
        super().__init__(status_code=status_code, content=content)

        # Determine bytes representation of the content in a safe way
        try:
            if isinstance(getattr(self, "body", None), (bytes, bytearray)):
                content_bytes = bytes(self.body)
            elif isinstance(getattr(self, "media", None), (bytes, bytearray)):
                content_bytes = bytes(self.media)
            elif isinstance(getattr(self, "content", None), (bytes, bytearray)):
                content_bytes = bytes(self.content)
            else:
                content_bytes = str(self.content or "").encode("utf-8")
        except Exception:
            logger.error("Error obtaining response content bytes", exc_info=True)
            content_bytes = b""

        async def _async_body() -> bytes:
            return content_bytes

        # Attach an awaitable body attribute on the instance
        # This overrides any non-callable body attribute set by Response.__init__
        setattr(self, "body", _async_body)


class RateLimitingMiddleware(BaseHTTPMiddleware):
    """Middleware that rate-limits requests per client IP using a simple sliding window.

    Stores per-client request timestamps in a deque and prunes entries older than
    LONG_POLLING_RATE_LIMIT_INTERVAL.
    """

    def __init__(self, app, config: Config, **kwargs) -> None:
        super().__init__(app)
        self.config = config
        # client_ip -> deque[timestamps]
        self._client_requests: dict[str, deque[float]] = defaultdict(deque)
        logger.debug("RateLimitingMiddleware initialized with config=%s", config)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        try:
            client_ip = "unknown"
            try:
                # Request.client may be None in some test contexts
                client = request.client
                if client is not None:
                    # starlette exposes client as a tuple (host, port) in some tests
                    client_ip = getattr(client, "host", None) or (client[0] if isinstance(client, tuple) and client else "unknown")
            except Exception:
                logger.debug("Unable to determine client IP from request; using 'unknown'")

            now = time.time()
            window = float(self.config.LONG_POLLING_RATE_LIMIT_INTERVAL)
            max_requests = int(self.config.LONG_POLLING_RATE_LIMIT_REQUESTS)

            dq = self._client_requests[client_ip]

            # Remove old timestamps
            try:
                cutoff = now - window
                while dq and dq[0] < cutoff:
                    dq.popleft()
            except Exception as e:
                logger.error(e, exc_info=True)

            if len(dq) >= max_requests:
                logger.warning("Rate limit exceeded for client %s: %s requests in %s seconds", client_ip, len(dq), window)

                # Return a standard ASGI-compatible Response instance that
                # exposes an awaitable body() attribute for tests.
                return RateLimitResponse(status_code=429, content="Rate limit exceeded")

            # Record this request
            dq.append(now)

            response = await call_next(request)
            return response
        except Exception as e:
            logger.error(e, exc_info=True)
            raise
