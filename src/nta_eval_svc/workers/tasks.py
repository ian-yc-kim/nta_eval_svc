from __future__ import annotations

import logging
import time
from typing import Optional

from celery.exceptions import Retry
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, func

from nta_eval_svc.workers.celery_app import celery_app
from nta_eval_svc.config import config as app_config
from nta_eval_svc.core.database import _build_engine
from nta_eval_svc.models.evaluation import EvaluationJob

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3, name="nta_eval_svc.workers.tasks.process_evaluation_job")
def process_evaluation_job(self, evaluation_job_id: str) -> Optional[str]:
    """Process an evaluation job by id, updating DB statuses as it proceeds.

    This task builds its own engine from configuration so it can run in worker
    processes independent of the FastAPI app process.
    """
    engine = None
    SessionLocal = None
    session = None
    try:
        # Build engine from current configuration
        engine = _build_engine(app_config.DATABASE_URL)
        SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

        session = SessionLocal()

        # Fetch job
        try:
            job = session.get(EvaluationJob, evaluation_job_id)
        except Exception as e:
            logger.error(e, exc_info=True)
            # If retrieval failed, do not retry here; let Celery handle root errors
            raise

        if job is None:
            logger.error("EvaluationJob not found: %s", evaluation_job_id)
            return None

        # Mark in-progress
        try:
            job.status = "in_progress"
            session.add(job)
            session.commit()
        except Exception as e:
            logger.error(e, exc_info=True)
            try:
                session.rollback()
            except Exception:
                logger.error("rollback failed", exc_info=True)
            raise

        # Simulate processing
        try:
            # short sleep for sample; real work would go here
            time.sleep(1)

            # On success mark completed
            try:
                job.status = "completed"
                job.completed_at = func.now()
                session.add(job)
                session.commit()
            except Exception as e:
                logger.error(e, exc_info=True)
                try:
                    session.rollback()
                except Exception:
                    logger.error("rollback failed", exc_info=True)
                raise

            return job.id

        except Exception as e:
            # Log the error with exception info
            logger.error(e, exc_info=True)

            # Attempt to update the job to failed (best-effort)
            try:
                # Refresh job state from DB if possible
                try:
                    session.refresh(job)
                except Exception:
                    # ignore refresh failures
                    pass
                job.status = "failed"
                job.error_message = str(e)[:4000]
                session.add(job)
                session.commit()
            except Exception as db_err:
                logger.error(db_err, exc_info=True)
                try:
                    session.rollback()
                except Exception:
                    logger.error("rollback failed", exc_info=True)

            # Decide on retrying
            # self.request.retries gives current retry count (0-based)
            retries = getattr(self.request, "retries", 0)
            max_retries = getattr(self, "max_retries", 0)

            if retries < max_retries:
                try:
                    # Retry after a short countdown
                    raise self.retry(countdown=5)
                except Retry:
                    # Celery signals retry via exception; re-raise to allow worker handling
                    raise
                except Exception:
                    # If retry mechanism itself failed, just return
                    return None
            else:
                # No retries left; return gracefully
                return None

    except Exception as outer_exc:
        # Unexpected outer errors should be logged
        logger.error(outer_exc, exc_info=True)
        # For unexpected errors, attempt to raise to let Celery handle (unless within retry path)
        raise
    finally:
        # Clean up session/engine
        try:
            if session is not None:
                session.close()
        except Exception as e:
            logger.error(e, exc_info=True)
