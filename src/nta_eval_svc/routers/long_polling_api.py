"""Long polling API router and endpoint implementation."""
from typing import Optional
import logging

from fastapi import APIRouter, HTTPException, Request, Query

from nta_eval_svc.config import config
from nta_eval_svc.core.database import SessionLocal
from nta_eval_svc.services.polling_service import ConnectionManager, LongPollingService

logger = logging.getLogger(__name__)

long_polling_api_router = APIRouter(prefix="/long-poll")

# Shared connection manager used across requests
connection_manager: ConnectionManager = ConnectionManager(config)

# Default DB session factory; tests may override the module-level polling_service
# to provide a session factory bound to the test database.
polling_service: LongPollingService = LongPollingService(SessionLocal, config, connection_manager)


@long_polling_api_router.post("/{evaluation_id}")
async def long_poll(
    evaluation_id: str,
    request: Request,
    timeout: Optional[int] = Query(None, ge=1),
):
    """Long-poll for an EvaluationJob by id.

    Uses the shared polling_service. Tests may override the module-level
    `polling_service` to bind to the test DB session factory.
    """
    try:
        # Derive client IP robustly; allow X-Forwarded-For header to aid tests
        client_ip = "unknown"
        try:
            # Prefer explicit header if present (useful for tests)
            xff = request.headers.get("x-forwarded-for")
            if xff:
                # use the first IP in the header
                client_ip = xff.split(",")[0].strip()
            else:
                client = request.client
                if client is not None:
                    client_ip = getattr(client, "host", None) or (client[0] if isinstance(client, tuple) and client else "unknown")
        except Exception as e:
            # Be explicit in logging any unexpected client extraction errors
            logger.error("Error extracting client IP: %s", e, exc_info=True)
            client_ip = "unknown"

        timeout_seconds = int(timeout) if timeout is not None else config.LONG_POLLING_DEFAULT_TIMEOUT

        result = await polling_service.poll_for_results(evaluation_id, timeout_seconds, client_ip)
        return result
    except HTTPException:
        # Let HTTPExceptions bubble up (status codes preserved)
        raise
    except Exception as e:
        # Unexpected errors should be logged with context and converted to 500
        logger.error("Unexpected error in long_poll endpoint: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


__all__ = ["long_polling_api_router", "connection_manager", "polling_service"]
