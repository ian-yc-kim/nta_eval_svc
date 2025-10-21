"""Long polling service implementation.

Implements ConnectionManager and LongPollingService with adaptive polling and
proper session handling per poll.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from typing import Callable, Optional

from fastapi import HTTPException
from sqlalchemy import select

from nta_eval_svc.config import Config
from nta_eval_svc.models.evaluation import EvaluationJob

logger = logging.getLogger(__name__)

# Capture asyncio.sleep at import time to avoid test monkeypatch recursion.
# Tests may monkeypatch asyncio.sleep; by using the captured reference we
# ensure our internal sleeps use the original implementation and avoid
# accidental recursive calls.
_asyncio_sleep = asyncio.sleep


class ConnectionManager:
    """Track active long-poll connections per client and globally.

    Uses a defaultdict of sets for per-client tracking and a set of
    (client_ip, evaluation_id) tuples for global tracking.
    """

    def __init__(self, config: Config) -> None:
        self.config = config
        self._client_connections: dict[str, set[str]] = defaultdict(set)
        self._global_connections: set[tuple[str, str]] = set()

    async def connect(self, client_ip: str, evaluation_id: str) -> None:
        connection_identifier = (client_ip, evaluation_id)
        try:
            # Global limit
            if len(self._global_connections) >= self.config.LONG_POLLING_GLOBAL_MAX_CONNECTIONS:
                logger.warning("Global connection limit exceeded: %s", len(self._global_connections))
                raise HTTPException(status_code=429, detail="Connection limit exceeded")

            # Per-client limit
            if len(self._client_connections[client_ip]) >= self.config.LONG_POLLING_MAX_CLIENT_CONNECTIONS:
                logger.warning("Client %s exceeded per-client connection limit: %s", client_ip, len(self._client_connections[client_ip]))
                raise HTTPException(status_code=429, detail="Connection limit exceeded")

            # Add connection
            self._global_connections.add(connection_identifier)
            self._client_connections[client_ip].add(evaluation_id)
            logger.debug("Connected %s for client %s", evaluation_id, client_ip)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(e, exc_info=True)
            # Wrap unexpected errors as 429 to avoid leaking internals to clients
            raise HTTPException(status_code=429, detail="Connection limit exceeded")

    async def disconnect(self, client_ip: str, evaluation_id: str) -> None:
        connection_identifier = (client_ip, evaluation_id)
        try:
            if connection_identifier in self._global_connections:
                self._global_connections.discard(connection_identifier)
            if evaluation_id in self._client_connections.get(client_ip, set()):
                self._client_connections[client_ip].discard(evaluation_id)
                if not self._client_connections[client_ip]:
                    # Clean up empty entries
                    del self._client_connections[client_ip]
            logger.debug("Disconnected %s for client %s", evaluation_id, client_ip)
        except Exception as e:
            logger.error(e, exc_info=True)
            # best-effort disconnect; do not raise


class LongPollingService:
    """Service to perform long polling for evaluation job results.

    It uses ConnectionManager to guard concurrent connections and polls the
    database using a fresh session on each poll to reflect latest state.
    """

    def __init__(
        self,
        db_session_factory: Callable[[], object],
        config: Config,
        connection_manager: ConnectionManager,
    ) -> None:
        self.db_session_factory = db_session_factory
        self.config = config
        self.connection_manager = connection_manager

    async def poll_for_results(self, evaluation_id: str, timeout_seconds: int, client_ip: str) -> dict:
        await self.connection_manager.connect(client_ip, evaluation_id)
        try:
            # Initial lookup using one session
            initial_session = None
            try:
                initial_session = self.db_session_factory()
                stmt = select(EvaluationJob).where(EvaluationJob.id == evaluation_id)
                result = initial_session.execute(stmt)
                job = result.scalar_one_or_none()
            except HTTPException:
                raise
            except Exception as e:
                logger.error(e, exc_info=True)
                # Treat DB failures as not found to avoid leaking details
                raise HTTPException(status_code=404, detail="Evaluation job not found")
            finally:
                try:
                    if initial_session is not None:
                        initial_session.close()
                except Exception:
                    logger.error("Failed closing initial DB session", exc_info=True)

            if job is None:
                raise HTTPException(status_code=404, detail="Evaluation job not found")

            # Determine job age from created_at
            try:
                job_created_at = job.created_at.timestamp()
            except Exception:
                # If created_at missing or malformed, use current time as fallback
                job_created_at = time.time()

            start_polling_loop_time = time.time()

            while True:
                current_time = time.time()
                time_elapsed_since_job_creation = current_time - job_created_at
                remaining_timeout = timeout_seconds - time_elapsed_since_job_creation

                # Safeguard: also enforce client provided timeout on total loop runtime
                if remaining_timeout <= 0 or (current_time - start_polling_loop_time) > timeout_seconds:
                    logger.debug("Long poll timeout for %s (remaining=%s)", evaluation_id, remaining_timeout)
                    return {"status": "timeout"}

                # Use a fresh session to get latest status
                session = None
                try:
                    session = self.db_session_factory()
                    stmt = select(EvaluationJob).where(EvaluationJob.id == evaluation_id)
                    result = session.execute(stmt)
                    job = result.scalar_one_or_none()
                except Exception as e:
                    logger.error(e, exc_info=True)
                    # On DB error, return timeout-like response to client
                    return {"status": "timeout"}
                finally:
                    try:
                        if session is not None:
                            session.close()
                    except Exception:
                        logger.error("Failed closing DB session in poll loop", exc_info=True)

                if job is None:
                    # If the job vanished, respond with 404
                    raise HTTPException(status_code=404, detail="Evaluation job not found")

                if job.status in ("completed", "failed"):
                    # Return relevant details
                    try:
                        completed_at = None
                        if getattr(job, "completed_at", None) is not None:
                            try:
                                completed_at = job.completed_at.isoformat()
                            except Exception:
                                completed_at = str(job.completed_at)

                        return {
                            "id": getattr(job, "id", evaluation_id),
                            "status": job.status,
                            "results": getattr(job, "results", None),
                            "error_message": getattr(job, "error_message", None),
                            "completed_at": completed_at,
                        }
                    except Exception as e:
                        logger.error(e, exc_info=True)
                        return {"status": "timeout"}

                # Adaptive sleep: smaller interval if remaining time is small
                sleep_for = min(self.config.LONG_POLLING_POLL_INTERVAL, max(0.01, remaining_timeout / 4))
                try:
                    # Use captured sleep function to avoid recursion if tests monkeypatch asyncio.sleep
                    await _asyncio_sleep(sleep_for)
                except Exception as e:
                    logger.error(e, exc_info=True)
                    # If sleep fails for any reason, break with timeout
                    return {"status": "timeout"}

        finally:
            # Ensure disconnect is always attempted
            try:
                await self.connection_manager.disconnect(client_ip, evaluation_id)
            except Exception as e:
                logger.error(e, exc_info=True)
