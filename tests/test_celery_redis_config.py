import importlib
import pytest


def reload_config(monkeypatch, set_env: dict | None = None, unset_env: list[str] | None = None):
    set_env = set_env or {}
    unset_env = unset_env or []

    # Unset requested environment variables first
    for key in unset_env:
        monkeypatch.delenv(key, raising=False)
    # Apply requested environment variables
    for k, v in set_env.items():
        monkeypatch.setenv(k, str(v))

    import nta_eval_svc.config as cfg
    importlib.reload(cfg)
    return cfg


def test_celery_redis_defaults(monkeypatch):
    # Ensure none of the celery/redis related env vars are set
    unset = [
        "REDIS_HOST",
        "REDIS_PORT",
        "CELERY_BROKER_URL",
        "CELERY_RESULT_BACKEND",
        "CELERY_TASK_SERIALIZER",
        "CELERY_RESULT_SERIALIZER",
        "CELERY_ACCEPT_CONTENT",
        "CELERY_TIMEZONE",
        "CELERY_ENABLE_UTC",
        "CELERY_TASK_TRACK_STARTED",
        "CELERY_WORKER_CONCURRENCY",
    ]
    cfg = reload_config(monkeypatch, unset_env=unset)
    c = cfg.Config()

    assert c.REDIS_HOST == "localhost"
    assert c.REDIS_PORT == 6379
    assert c.CELERY_BROKER_URL == "redis://localhost:6379/0"
    assert c.CELERY_RESULT_BACKEND == "redis://localhost:6379/0"
    assert c.CELERY_TASK_SERIALIZER == "json"
    assert c.CELERY_RESULT_SERIALIZER == "json"
    assert c.CELERY_ACCEPT_CONTENT == "json"
    assert c.CELERY_TIMEZONE == "UTC"
    assert c.CELERY_ENABLE_UTC is True
    assert c.CELERY_TASK_TRACK_STARTED is True
    assert c.CELERY_WORKER_CONCURRENCY == 4


def test_celery_redis_env_overrides(monkeypatch):
    # Provide overrides for Redis host/port and other celery settings
    env = {
        "REDIS_HOST": "redis.example",
        "REDIS_PORT": "6380",
        # Do not set CELERY_BROKER_URL to ensure derived URL uses REDIS_* values
        "CELERY_RESULT_BACKEND": "redis://custom-backend:6379/2",
        "CELERY_TASK_SERIALIZER": "msgpack",
        "CELERY_RESULT_SERIALIZER": "msgpack",
        "CELERY_ACCEPT_CONTENT": "msgpack",
        "CELERY_TIMEZONE": "America/New_York",
        "CELERY_ENABLE_UTC": "false",
        "CELERY_TASK_TRACK_STARTED": "0",
        "CELERY_WORKER_CONCURRENCY": "8",
    }
    cfg = reload_config(monkeypatch, set_env=env)
    c = cfg.Config()

    assert c.REDIS_HOST == "redis.example"
    assert c.REDIS_PORT == 6380
    # Broker URL should be derived from REDIS_HOST and REDIS_PORT when not explicitly set
    assert c.CELERY_BROKER_URL == "redis://redis.example:6380/0"
    # Result backend should reflect explicit override
    assert c.CELERY_RESULT_BACKEND == "redis://custom-backend:6379/2"
    assert c.CELERY_TASK_SERIALIZER == "msgpack"
    assert c.CELERY_RESULT_SERIALIZER == "msgpack"
    assert c.CELERY_ACCEPT_CONTENT == "msgpack"
    assert c.CELERY_TIMEZONE == "America/New_York"
    assert c.CELERY_ENABLE_UTC is False
    assert c.CELERY_TASK_TRACK_STARTED is False
    assert c.CELERY_WORKER_CONCURRENCY == 8
