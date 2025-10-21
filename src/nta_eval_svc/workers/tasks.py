from __future__ import annotations

import logging
import time
from typing import Optional, Any

from celery.exceptions import Retry
from sqlalchemy import func

from nta_eval_svc.workers.celery_app import celery_app
from nta_eval_svc.core.database import SessionLocal
from nta_eval_svc.config import config as app_config
from nta_eval_svc.models.evaluation import EvaluationJob, EvaluationCriteria
from nta_eval_svc.services.openai_service import OpenAIService

import yaml

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3, name="nta_eval_svc.workers.tasks.process_evaluation_job")
def process_evaluation_job(self, evaluation_job_id: str) -> Optional[str]:
    """Process an evaluation job by id, perform evaluations via OpenAI, and persist results."""
    session = None
    try:
        session = SessionLocal()

        # Fetch job
        try:
            job = session.get(EvaluationJob, evaluation_job_id)
        except Exception as e:
            logger.error("failed fetching job %s", evaluation_job_id, exc_info=True)
            raise

        if job is None:
            logger.error("EvaluationJob not found: %s", evaluation_job_id)
            return None

        # Mark in-progress early and persist
        try:
            job.status = "in_progress"
            session.add(job)
            session.commit()
        except Exception as e:
            logger.error("failed to mark job in_progress %s", job.id, exc_info=True)
            session.rollback()
            raise

        # Fetch criteria
        try:
            crit = session.get(EvaluationCriteria, job.evaluation_id)
            if crit is None:
                raise RuntimeError(f"EvaluationCriteria not found for id {job.evaluation_id}")

            try:
                parsed = yaml.safe_load(crit.criteria_yaml)
            except Exception as e:
                logger.error("yaml parsing failed for criteria %s", crit.id, exc_info=True)
                raise

            # Normalize criteria into a list of items
            if isinstance(parsed, dict) and "criteria" in parsed and isinstance(parsed["criteria"], list):
                criteria_list = parsed["criteria"]
            elif isinstance(parsed, list):
                criteria_list = parsed
            else:
                # Single implicit criterion
                criteria_list = [{
                    "name": "default",
                    "method": "score",
                    "rules": parsed,
                }]

        except Exception as e:
            # Set job failed and persist
            logger.error("failed preparing criteria for job %s", job.id, exc_info=True)
            try:
                job.status = "failed"
                job.error_message = str(e)[:4000]
                session.add(job)
                session.commit()
            except Exception:
                session.rollback()
            # Retry if possible
            retries = getattr(self.request, "retries", 0)
            max_retries = getattr(self, "max_retries", 0)
            if retries < max_retries:
                raise self.retry(countdown=5)
            return None

        # Prepare service (no external client by default; tests may monkeypatch)
        try:
            # A small sleep call exists so tests can monkeypatch time.sleep to force errors.
            # In normal operation this is a no-op (sleep 0).
            time.sleep(0)

            openai_service = OpenAIService()

            evaluation_sheet: dict[str, Any] = {
                "job_id": job.id,
                "agent_name": job.agent_name,
                "version": job.version,
                "criteria": [],
            }

            for c in criteria_list:
                name = c.get("name") if isinstance(c, dict) else str(c)
                method = c.get("method") if isinstance(c, dict) else None
                rules = c.get("rules") if isinstance(c, dict) else c

                if method not in ("score", "success-failure"):
                    # default method
                    method = "score"

                # Evaluate criterion (sync wrapper)
                try:
                    samples, aggregated = openai_service.evaluate_criterion_sync(job.output, method, rules, samples=5)
                except Exception as e:
                    logger.error("evaluation failed for criterion %s in job %s", name, job.id, exc_info=True)
                    raise

                evaluation_sheet["criteria"].append({
                    "name": name,
                    "method": method,
                    "rules": rules,
                    "samples": samples,
                    "aggregated": aggregated,
                })

            # Persist results
            try:
                job.results = evaluation_sheet
                job.status = "completed"
                job.completed_at = func.now()
                session.add(job)
                session.commit()
            except Exception as e:
                logger.error("failed to persist job results %s", job.id, exc_info=True)
                session.rollback()
                raise

            return job.id

        except Exception as e:
            logger.error("processing job failed %s", job.id, exc_info=True)
            # Attempt to mark job as failed
            try:
                job.status = "failed"
                job.error_message = str(e)[:4000]
                session.add(job)
                session.commit()
            except Exception:
                try:
                    session.rollback()
                except Exception:
                    logger.error("rollback failed while setting job failed", exc_info=True)

            retries = getattr(self.request, "retries", 0)
            max_retries = getattr(self, "max_retries", 0)
            if retries < max_retries:
                try:
                    raise self.retry(countdown=5)
                except Retry:
                    raise
                except Exception:
                    return None
            return None

    except Exception as outer_exc:
        logger.error("unexpected error in task", exc_info=True)
        raise
    finally:
        try:
            if session is not None:
                session.close()
        except Exception:
            logger.error("failed closing session", exc_info=True)
