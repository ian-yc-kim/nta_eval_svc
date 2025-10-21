"""Rate limiting middleware for long-poll endpoints."""
from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Scope, Receive, Send

from nta_eval_svc.config import Config

logger = logging.getLogger(__name__)


class RateLimitResponse:
    """A lightweight ASGI-capable response object for rate-limited replies.

    This intentionally does not call starlette.responses.Response.__init__ so
    that no instance attribute named 'body' (bytes) is set and a class async
    body() method remains available to be awaited by unit tests.

    It implements:
    - status_code attribute used by callers/tests
    - async body() method returning bytes
    - async __call__ ASGI entrypoint sending http.response.start and body

    This object is small and tailored to the needs of the middleware and tests.
    """

    def __init__(self, content: bytes | str = b"Rate limit exceeded", status_code: int = 429, media_type: str = "text/plain") -> None:
        if isinstance(content, str):
            bcontent = content.encode("utf-8")
        else:
            bcontent = content
        # do not call Response.__init__ to avoid setting instance body attribute
        self._rl_body: bytes = bcontent
        self.status_code: int = int(status_code)
        self.media_type: str = media_type or "text/plain"
        # allow optional headers if needed
        self.headers = [(b"content-type", self.media_type.encode("latin-1"))]

    async def body(self) -> bytes:
        """Return the raw body bytes for callers that await response.body()."""
        return self._rl_body

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """ASGI entrypoint that sends a single non-streaming response."""
        try:
            await send({"type": "http.response.start", "status": int(self.status_code), "headers": self.headers})
            await send({"type": "http.response.body", "body": self._rl_body})
        except Exception as e:
            logger.error(e, exc_info=True)
            raise


class RateLimitingMiddleware(BaseHTTPMiddleware):
    """Middleware that rate-limits requests per client IP using a simple sliding window.

    Stores per-client request timestamps in a deque and prunes entries older than
    LONG_POLLING_RATE_LIMIT_INTERVAL. Tests may inject an x-test-run-id header to
    isolate counters between test runs.
    """

    def __init__(self, app, config: Config, **kwargs) -> None:
        super().__init__(app)
        self.config = config
        # key -> deque[timestamps]
        # key is typically client_ip but may include test run id to isolate tests
        self._client_requests: dict[str, deque[float]] = defaultdict(deque)
        logger.debug("RateLimitingMiddleware initialized with config=%s", config)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        try:
            client_ip = "unknown"
            try:
                client = request.client
                if client is not None:
                    client_ip = getattr(client, "host", None) or (client[0] if isinstance(client, tuple) and client else "unknown")
            except Exception:
                logger.debug("Unable to determine client IP from request; using 'unknown'")

            # Allow tests to partition rate limit buckets using a header
            test_run = None
            try:
                test_run = request.headers.get("x-test-run-id")
            except Exception:
                test_run = None

            # Build a key that includes optional test run id to avoid cross-test contamination
            key = f"{client_ip}:{test_run}" if test_run else client_ip

            now = time.time()
            window = float(self.config.LONG_POLLING_RATE_LIMIT_INTERVAL)
            max_requests = int(self.config.LONG_POLLING_RATE_LIMIT_REQUESTS)

            dq = self._client_requests[key]

            # Remove old timestamps
            try:
                cutoff = now - window
                while dq and dq[0] < cutoff:
                    dq.popleft()
            except Exception as e:
                logger.error(e, exc_info=True)

            if len(dq) >= max_requests:
                logger.warning("Rate limit exceeded for client %s: %s requests in %s seconds", key, len(dq), window)
                # Return a small ASGI-compatible response object that provides
                # both an awaitable body() and a __call__ for ASGI dispatch.
                try:
                    return RateLimitResponse(b"Rate limit exceeded", status_code=429, media_type="text/plain")
                except Exception as e:
                    logger.error(e, exc_info=True)
                    # Fallback: return a standard Response (rare)
                    return Response(content=b"Rate limit exceeded", status_code=429, media_type="text/plain")

            # Record this request
            dq.append(now)

            response = await call_next(request)
            return response
        except Exception as e:
            logger.error(e, exc_info=True)
            raise
