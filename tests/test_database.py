import importlib
import threading

import pytest
from sqlalchemy import text


def reload_modules_with_env(monkeypatch, env: dict):
    for k, v in env.items():
        monkeypatch.setenv(k, str(v))
    # Reload config then database module to apply new env
    import nta_eval_svc.config as cfg
    importlib.reload(cfg)
    import nta_eval_svc.core.database as db
    importlib.reload(db)
    return cfg, db


def test_env_config_loading(monkeypatch):
    cfg, db = reload_modules_with_env(
        monkeypatch,
        {
            "DATABASE_URL": "sqlite:///:memory:",
            "DB_ECHO": "true",
            "DB_POOL_RECYCLE": "100",
        },
    )

    engine = db.get_engine()
    assert cfg.config.DB_ECHO is True
    assert cfg.config.DB_POOL_RECYCLE == 100
    assert engine.dialect.name == "sqlite"
    # For in-memory sqlite we expect a StaticPool to be used
    assert engine.pool is not None


def test_connection_establishment(monkeypatch):
    # Ensure default in-memory DB
    _, db = reload_modules_with_env(monkeypatch, {"DATABASE_URL": "sqlite:///:memory:"})
    assert db.check_database_connection() is True


def _ensure_demo_table(db):
    engine = db.get_engine()
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS demo (id INTEGER PRIMARY KEY, name VARCHAR(50))"))
        try:
            conn.commit()
        except Exception:
            pass


def test_session_commit_and_cleanup(monkeypatch):
    _, db = reload_modules_with_env(monkeypatch, {"DATABASE_URL": "sqlite:///:memory:"})
    _ensure_demo_table(db)

    # Insert within managed session and let it commit
    g = db.get_db()
    session = next(g)
    session.execute(text("INSERT INTO demo (name) VALUES (:name)"), {"name": "alice"})
    # Resume generator to perform commit and close
    with pytest.raises(StopIteration):
        next(g)

    # Verify
    engine = db.get_engine()
    with engine.connect() as conn:
        res = conn.execute(text("SELECT COUNT(*) FROM demo"))
        count = res.scalar_one()
    assert count == 1


def test_session_rollback_on_exception(monkeypatch):
    _, db = reload_modules_with_env(monkeypatch, {"DATABASE_URL": "sqlite:///:memory:"})
    _ensure_demo_table(db)

    # Clean slate
    engine = db.get_engine()
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM demo"))
        try:
            conn.commit()
        except Exception:
            pass

    # Perform insert then force exception to trigger rollback
    g = db.get_db()
    session = next(g)
    session.execute(text("INSERT INTO demo (name) VALUES ('bob')"))

    with pytest.raises(RuntimeError):
        g.throw(RuntimeError("boom"))

    # Verify rollback
    with engine.connect() as conn:
        res = conn.execute(text("SELECT COUNT(*) FROM demo"))
        count = res.scalar_one()
    assert count == 0


def test_concurrent_access_pooling_behavior(monkeypatch):
    _, db = reload_modules_with_env(monkeypatch, {"DATABASE_URL": "sqlite:///:memory:"})

    results: list[bool] = []
    errors: list[Exception] = []

    def worker():
        try:
            g = db.get_db()
            s = next(g)
            s.execute(text("SELECT 1"))
            # Resume generator to commit/close paths
            try:
                next(g)
            except StopIteration:
                pass
            results.append(True)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Errors occurred in threads: {errors}"
    assert len(results) == 5


def test_fastapi_dependency_override(client):
    # The conftest client fixture overrides get_db for the app
    from nta_eval_svc.app import app
    from nta_eval_svc.models.base import get_db as base_get_db

    assert base_get_db in app.dependency_overrides
    assert callable(app.dependency_overrides[base_get_db])


def test_connection_failure_handling(monkeypatch):
    # Point to a sqlite file in a non-existent directory to force failure
    bad_path = "sqlite:////this/path/does/not/exist/db.sqlite3"
    _, db = reload_modules_with_env(monkeypatch, {"DATABASE_URL": bad_path})
    ok = db.check_database_connection()
    assert ok is False
