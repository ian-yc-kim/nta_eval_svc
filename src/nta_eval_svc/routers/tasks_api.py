import logging
from fastapi import APIRouter, HTTPException

from nta_eval_svc.workers import process_evaluation_job

logger = logging.getLogger(__name__)

tasks_api_router = APIRouter()


@tasks_api_router.post("/tasks/dispatch/{job_id}")
async def dispatch_task(job_id: str):
    """Dispatch a Celery task to process an evaluation job by id.

    This endpoint enqueues the process_evaluation_job Celery task by calling
    its delay() method. Any exceptions during enqueue are logged and a 500
    returned.
    """
    try:
        # Call Celery task asynchronously
        process_evaluation_job.delay(job_id)
        return {"enqueued": True, "job_id": job_id}
    except Exception as e:
        logger.error(e, exc_info=True)
        # Do not expose internal exception details
        raise HTTPException(status_code=500, detail="failed to enqueue task")
