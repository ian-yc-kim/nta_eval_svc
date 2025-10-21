import importlib
import pytest


def reload_config(monkeypatch, set_env: dict | None = None, unset_env: list[str] | None = None):
    set_env = set_env or {}
    unset_env = unset_env or []

    for key in unset_env:
        monkeypatch.delenv(key, raising=False)
    for k, v in set_env.items():
        monkeypatch.setenv(k, str(v))

    import nta_eval_svc.config as cfg
    importlib.reload(cfg)
    return cfg


def test_long_polling_defaults(monkeypatch):
    unset = [
        "LONG_POLLING_DEFAULT_TIMEOUT",
        "LONG_POLLING_POLL_INTERVAL",
        "LONG_POLLING_MAX_CLIENT_CONNECTIONS",
        "LONG_POLLING_GLOBAL_MAX_CONNECTIONS",
        "LONG_POLLING_RATE_LIMIT_INTERVAL",
        "LONG_POLLING_RATE_LIMIT_REQUESTS",
    ]
    cfg = reload_config(monkeypatch, unset_env=unset)
    c = cfg.Config()

    assert c.LONG_POLLING_DEFAULT_TIMEOUT == 30
    assert c.LONG_POLLING_POLL_INTERVAL == 0.5
    assert c.LONG_POLLING_MAX_CLIENT_CONNECTIONS == 5
    assert c.LONG_POLLING_GLOBAL_MAX_CONNECTIONS == 1000
    assert c.LONG_POLLING_RATE_LIMIT_INTERVAL == 60
    assert c.LONG_POLLING_RATE_LIMIT_REQUESTS == 100


def test_long_polling_env_overrides(monkeypatch):
    env = {
        "LONG_POLLING_DEFAULT_TIMEOUT": "45",
        "LONG_POLLING_POLL_INTERVAL": "0.25",
        "LONG_POLLING_MAX_CLIENT_CONNECTIONS": "10",
        "LONG_POLLING_GLOBAL_MAX_CONNECTIONS": "500",
        "LONG_POLLING_RATE_LIMIT_INTERVAL": "120",
        "LONG_POLLING_RATE_LIMIT_REQUESTS": "250",
    }
    cfg = reload_config(monkeypatch, set_env=env)
    c = cfg.Config()

    assert c.LONG_POLLING_DEFAULT_TIMEOUT == 45
    assert abs(c.LONG_POLLING_POLL_INTERVAL - 0.25) < 1e-9
    assert c.LONG_POLLING_MAX_CLIENT_CONNECTIONS == 10
    assert c.LONG_POLLING_GLOBAL_MAX_CONNECTIONS == 500
    assert c.LONG_POLLING_RATE_LIMIT_INTERVAL == 120
    assert c.LONG_POLLING_RATE_LIMIT_REQUESTS == 250
