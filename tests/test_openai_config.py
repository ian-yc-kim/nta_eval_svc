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


def test_openai_model_default(monkeypatch):
    cfg = reload_config(monkeypatch, unset_env=["OPENAI_MODEL"])  # ensure not set
    c = cfg.Config()
    assert c.OPENAI_MODEL == "gpt-3.5-turbo"


def test_openai_model_from_env(monkeypatch):
    cfg = reload_config(monkeypatch, set_env={"OPENAI_MODEL": "gpt-4o"})
    c = cfg.Config()
    assert c.OPENAI_MODEL == "gpt-4o"


@pytest.mark.parametrize("key_value", ["", "   "])
def test_openai_api_key_empty_raises(monkeypatch, key_value):
    cfg = reload_config(monkeypatch, set_env={"OPENAI_API_KEY": key_value})
    c = cfg.Config()
    with pytest.raises(ValueError):
        _ = c.OPENAI_API_KEY


def test_openai_api_key_missing_raises(monkeypatch):
    cfg = reload_config(monkeypatch, unset_env=["OPENAI_API_KEY"])  # ensure missing
    c = cfg.Config()
    with pytest.raises(ValueError):
        _ = c.OPENAI_API_KEY


def test_openai_api_key_present(monkeypatch):
    cfg = reload_config(monkeypatch, set_env={"OPENAI_API_KEY": "sk-test-123"})
    c = cfg.Config()
    assert c.OPENAI_API_KEY == "sk-test-123"


def test_backward_compatibility_constants(monkeypatch):
    # Ensure importing config without OPENAI vars still works and module-level constants remain
    cfg = reload_config(monkeypatch, unset_env=["OPENAI_API_KEY", "OPENAI_MODEL"]) 
    # Accessing constants should be fine
    assert hasattr(cfg, "DATABASE_URL")
    assert hasattr(cfg, "SERVICE_PORT")
    # Accessing api key property should raise since it's unset
    assert hasattr(cfg.config, "OPENAI_MODEL")
    with pytest.raises(ValueError):
        _ = cfg.config.OPENAI_API_KEY
