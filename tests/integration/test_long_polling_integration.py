import threading
import time
import uuid

import pytest

from nta_eval_svc.config import config
from nta_eval_svc.routers import long_polling_api
from nta_eval_svc.models.evaluation import EvaluationCriteria, EvaluationJob


def _create_criteria_and_job(db_session, status: str = "pending", results=None, job_id: str | None = None):
    # Ensure each criteria has a unique agent_name to avoid UNIQUE constraint collisions
    unique_agent = f"agentx-{uuid.uuid4().hex[:8]}"
    crit = EvaluationCriteria(agent_name=unique_agent, version=1, criteria_yaml="x")
    db_session.add(crit)
    db_session.commit()
    if job_id is None:
        job_id = str(uuid.uuid4())
    job = EvaluationJob(
        id=job_id,
        evaluation_id=crit.id,
        agent_name=crit.agent_name,
        version=crit.version,
        prompt="p",
        status=status,
        results=results,
    )
    db_session.add(job)
    db_session.commit()
    return job


@pytest.fixture(autouse=True)
def _speed_up_poll_interval(monkeypatch):
    # Make polls fast in tests
    original = config.LONG_POLLING_POLL_INTERVAL
    monkeypatch.setattr(config, "LONG_POLLING_POLL_INTERVAL", 0.01)
    yield
    monkeypatch.setattr(config, "LONG_POLLING_POLL_INTERVAL", original)


def _bind_polling_service_to_test_db(session_local):
    # Override module-level polling_service to use test session factory
    # session_local is the fixture that returns a sessionmaker
    long_polling_api.polling_service = long_polling_api.LongPollingService(session_local, config, long_polling_api.connection_manager)


def test_completed_immediate(client, db_session, session_local):
    _bind_polling_service_to_test_db(session_local)

    job = _create_criteria_and_job(db_session, status="completed", results={"a": 1})

    resp = client.post(f"/api/long-poll/{job.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["results"] == {"a": 1}


def test_pending_completes_quickly(client, db_session, session_local):
    _bind_polling_service_to_test_db(session_local)

    job = _create_criteria_and_job(db_session, status="pending")

    # Background thread will mark job completed after short delay
    def mark_completed():
        time.sleep(0.05)
        s = session_local()
        try:
            j = s.get(EvaluationJob, job.id)
            j.status = "completed"
            j.results = {"ok": True}
            s.commit()
        finally:
            s.close()

    t = threading.Thread(target=mark_completed)
    t.start()

    resp = client.post(f"/api/long-poll/{job.id}?timeout=5")
    t.join()
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["results"] == {"ok": True}


def test_pending_times_out(client, db_session, session_local):
    _bind_polling_service_to_test_db(session_local)

    job = _create_criteria_and_job(db_session, status="pending")

    # Use small timeout to force timeout
    resp = client.post(f"/api/long-poll/{job.id}?timeout=1")
    assert resp.status_code == 200
    assert resp.json() == {"status": "timeout"}


def test_404_for_missing_job(client, session_local):
    _bind_polling_service_to_test_db(session_local)

    missing_id = str(uuid.uuid4())
    resp = client.post(f"/api/long-poll/{missing_id}")
    assert resp.status_code == 404


def test_per_client_connection_limit_enforced(client, db_session, session_local, monkeypatch):
    # Bind service to test DB and reduce per-client limit
    _bind_polling_service_to_test_db(session_local)
    monkeypatch.setattr(config, "LONG_POLLING_MAX_CLIENT_CONNECTIONS", 1)

    job1 = _create_criteria_and_job(db_session, status="pending")
    job2 = _create_criteria_and_job(db_session, status="pending")

    # Start first request in background (will block)
    results = {}

    def call_first():
        r = client.post(f"/api/long-poll/{job1.id}")
        results["first"] = r

    t = threading.Thread(target=call_first)
    t.start()

    # Wait until connection manager reports a connection for the test client
    # Use a short spin-wait to avoid flaky fixed sleeps
    wait_deadline = time.time() + 2.0
    client_key_fragment = "testclient"
    while time.time() < wait_deadline:
        # connection_manager exposes public API for test introspection
        try:
            # try to find any connections; ConnectionManager may provide a method
            # fall back to checking internal dict if method not present
            conn_count = 0
            if hasattr(long_polling_api.connection_manager, "get_active_count_for_client"):
                conn_count = long_polling_api.connection_manager.get_active_count_for_client(client_key_fragment)
            elif hasattr(long_polling_api.connection_manager, "_connections"):
                # best-effort internal inspection for tests
                conn_count = sum(1 for k in long_polling_api.connection_manager._connections if client_key_fragment in k)
            if conn_count >= 1:
                break
        except Exception:
            pass
        time.sleep(0.01)

    # Second request from same client should be rejected due to per-client limit
    r2 = client.post(f"/api/long-poll/{job2.id}")
    assert r2.status_code == 429

    # Cleanup: mark first job completed so background request finishes
    s = session_local()
    try:
        j = s.get(EvaluationJob, job1.id)
        j.status = "completed"
        j.results = {"done": True}
        s.commit()
    finally:
        s.close()

    t.join(timeout=2)
    assert "first" in results
    assert results["first"].status_code == 200


def test_rate_limiting_enforced(client, db_session, session_local, monkeypatch):
    _bind_polling_service_to_test_db(session_local)

    # Configure rate limit low using monkeypatch for test isolation
    monkeypatch.setattr(config, "LONG_POLLING_RATE_LIMIT_INTERVAL", 60)
    monkeypatch.setattr(config, "LONG_POLLING_RATE_LIMIT_REQUESTS", 2)

    # Create completed jobs so requests return immediately
    j1 = _create_criteria_and_job(db_session, status="completed", results={})
    j2 = _create_criteria_and_job(db_session, status="completed", results={})
    j3 = _create_criteria_and_job(db_session, status="completed", results={})

    # Use a test-run header to isolate this test's rate limit counters
    hdr = {"x-test-run-id": uuid.uuid4().hex}

    r1 = client.post(f"/api/long-poll/{j1.id}", headers=hdr)
    assert r1.status_code == 200
    r2 = client.post(f"/api/long-poll/{j2.id}", headers=hdr)
    assert r2.status_code == 200
    r3 = client.post(f"/api/long-poll/{j3.id}", headers=hdr)
    # Third request should hit rate limiter
    assert r3.status_code == 429
