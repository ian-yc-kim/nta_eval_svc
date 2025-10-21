import asyncio
import datetime
from collections import deque

import pytest

from nta_eval_svc.config import Config
from nta_eval_svc.services.polling_service import ConnectionManager, LongPollingService
from fastapi import HTTPException
from starlette.responses import Response


class FakeJob:
    def __init__(self, id: str, status: str, created_at: datetime.datetime, results=None, error_message=None, completed_at=None):
        self.id = id
        self.status = status
        self.created_at = created_at
        self.results = results
        self.error_message = error_message
        self.completed_at = completed_at


class FakeExecuteResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class FakeSession:
    def __init__(self, result_value):
        # result_value can be a callable to produce dynamic results
        self._result_value = result_value
        self.closed = False

    def execute(self, stmt):
        val = self._result_value() if callable(self._result_value) else self._result_value
        return FakeExecuteResult(val)

    def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_connection_manager_connect_disconnect():
    cfg = Config()
    cm = ConnectionManager(cfg)

    await cm.connect("1.2.3.4", "eval1")
    assert ("1.2.3.4", "eval1") in cm._global_connections
    assert "eval1" in cm._client_connections["1.2.3.4"]

    await cm.disconnect("1.2.3.4", "eval1")
    assert ("1.2.3.4", "eval1") not in cm._global_connections
    assert "1.2.3.4" not in cm._client_connections


@pytest.mark.asyncio
async def test_connection_manager_enforce_limits():
    cfg = Config()
    cfg.LONG_POLLING_GLOBAL_MAX_CONNECTIONS = 1
    cfg.LONG_POLLING_MAX_CLIENT_CONNECTIONS = 1
    cm = ConnectionManager(cfg)

    # First connect should succeed
    await cm.connect("1.1.1.1", "a")

    # Second connect globally should fail
    with pytest.raises(HTTPException) as exc:
        await cm.connect("2.2.2.2", "b")
    assert exc.value.status_code == 429

    # Disconnect first then test per-client limit
    await cm.disconnect("1.1.1.1", "a")
    # Fill per-client
    await cm.connect("3.3.3.3", "x")
    with pytest.raises(HTTPException):
        await cm.connect("3.3.3.3", "y")


@pytest.mark.asyncio
async def test_long_poll_service_immediate_completed_and_disconnect_called(monkeypatch):
    cfg = Config()
    # Make small interval to make tests deterministic
    cfg.LONG_POLLING_POLL_INTERVAL = 0.1

    # Prepare a job already completed
    created_at = datetime.datetime.utcnow() - datetime.timedelta(seconds=1)
    job = FakeJob(id="job1", status="completed", created_at=created_at, results={"a": 1}, completed_at=created_at)

    # DB factory returns a session that always yields the completed job
    def session_factory():
        return FakeSession(job)

    class MockCM:
        def __init__(self):
            self.connected = False
            self.disconnected = False

        async def connect(self, ip, eid):
            self.connected = True

        async def disconnect(self, ip, eid):
            self.disconnected = True

    cm = MockCM()
    svc = LongPollingService(session_factory, cfg, cm)

    result = await svc.poll_for_results("job1", timeout_seconds=10, client_ip="9.9.9.9")
    assert result["status"] == "completed"
    assert result["results"] == {"a": 1}
    assert cm.connected is True
    assert cm.disconnected is True


@pytest.mark.asyncio
async def test_long_poll_service_404_when_not_found(monkeypatch):
    cfg = Config()

    def session_factory():
        return FakeSession(None)

    class MockCM:
        async def connect(self, ip, eid):
            pass

        async def disconnect(self, ip, eid):
            pass

    svc = LongPollingService(session_factory, cfg, MockCM())

    with pytest.raises(HTTPException) as exc:
        await svc.poll_for_results("doesnotexist", timeout_seconds=5, client_ip="1.2.3.4")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_long_poll_service_timeout_based_on_job_age(monkeypatch):
    cfg = Config()
    cfg.LONG_POLLING_POLL_INTERVAL = 0.01

    # Create a job that was created long ago so remaining timeout <= 0
    created_at = datetime.datetime.utcnow() - datetime.timedelta(seconds=100)
    job = FakeJob(id="oldjob", status="pending", created_at=created_at)

    def session_factory():
        return FakeSession(job)

    class MockCM:
        async def connect(self, ip, eid):
            pass

        async def disconnect(self, ip, eid):
            pass

    svc = LongPollingService(session_factory, cfg, MockCM())

    result = await svc.poll_for_results("oldjob", timeout_seconds=5, client_ip="1.1.1.1")
    assert result == {"status": "timeout"}


@pytest.mark.asyncio
async def test_long_poll_service_polls_until_completion(monkeypatch):
    cfg = Config()
    cfg.LONG_POLLING_POLL_INTERVAL = 0.01

    # Simulate job that is pending twice then completed
    created_at = datetime.datetime.utcnow()
    calls = {"count": 0}

    def result_provider():
        calls["count"] += 1
        if calls["count"] < 3:
            return FakeJob(id="j", status="pending", created_at=created_at)
        else:
            return FakeJob(id="j", status="completed", created_at=created_at, results={"ok": True}, completed_at=datetime.datetime.utcnow())

    def session_factory():
        return FakeSession(result_provider)

    # Patch asyncio.sleep to avoid real delays
    async def fast_sleep(_):
        await asyncio.sleep(0)

    monkeypatch.setattr("asyncio.sleep", fast_sleep)

    class MockCM:
        def __init__(self):
            self.disconnected = False

        async def connect(self, ip, eid):
            pass

        async def disconnect(self, ip, eid):
            self.disconnected = True

    cm = MockCM()
    svc = LongPollingService(session_factory, cfg, cm)

    result = await svc.poll_for_results("j", timeout_seconds=10, client_ip="5.5.5.5")
    assert result["status"] == "completed"
    assert result["results"] == {"ok": True}
    assert cm.disconnected is True
