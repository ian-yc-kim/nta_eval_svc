from celery import Celery
import logging

from nta_eval_svc.config import config as app_config

logger = logging.getLogger(__name__)


def _make_celery() -> Celery:
    """Create and configure Celery application based on Config."""
    celery = Celery("nta_eval_svc")

    # Basic configuration derived from application config
    celery.conf.broker_url = app_config.CELERY_BROKER_URL
    celery.conf.result_backend = app_config.CELERY_RESULT_BACKEND
    celery.conf.task_serializer = app_config.CELERY_TASK_SERIALIZER
    celery.conf.result_serializer = app_config.CELERY_RESULT_SERIALIZER
    celery.conf.accept_content = [c.strip() for c in app_config.CELERY_ACCEPT_CONTENT.split(",") if c.strip()]
    celery.conf.timezone = app_config.CELERY_TIMEZONE
    celery.conf.enable_utc = app_config.CELERY_ENABLE_UTC
    celery.conf.task_track_started = app_config.CELERY_TASK_TRACK_STARTED

    # Ensure Celery will attempt to reconnect on startup
    celery.conf.broker_connection_retry_on_startup = True

    # Include our tasks package so workers can discover them
    celery.conf.include = ["nta_eval_svc.workers.tasks"]

    # Log basic info
    logger.debug("Created Celery app with broker %s", app_config.CELERY_BROKER_URL)
    return celery


celery_app = _make_celery()
