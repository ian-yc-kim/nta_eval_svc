"""Middleware skeletons for long polling rate limiting."""
from __future__ import annotations

import logging
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from nta_eval_svc.config import Config

logger = logging.getLogger(__name__)


class RateLimitingMiddleware(BaseHTTPMiddleware):
    """Skeleton middleware for rate limiting long-polling endpoints.

    Currently a pass-through; future implementation will enforce per-client and
    global rate limits using values from Config.
    """

    def __init__(self, app, config: Config, **kwargs) -> None:
        super().__init__(app)
        self.config = config
        logger.debug("RateLimitingMiddleware initialized with config=%s", config)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        try:
            # Placeholder: rate limiting logic will go here
            return await call_next(request)
        except Exception as e:
            logger.error(e, exc_info=True)
            # Re-raise to let FastAPI handle response formatting
            raise
