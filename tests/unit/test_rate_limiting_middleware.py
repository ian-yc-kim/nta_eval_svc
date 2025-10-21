import asyncio
import time

import pytest

from starlette.requests import Request
from starlette.responses import Response

from nta_eval_svc.middleware import RateLimitingMiddleware
from nta_eval_svc.config import Config


class DummyApp:
    async def __call__(self, scope, receive, send):
        # not used in tests
        pass


@pytest.mark.asyncio
async def test_requests_within_limit_pass(monkeypatch):
    cfg = Config()
    cfg.LONG_POLLING_RATE_LIMIT_INTERVAL = 60
    cfg.LONG_POLLING_RATE_LIMIT_REQUESTS = 3

    middleware = RateLimitingMiddleware(DummyApp(), cfg)

    async def call_next(request):
        return Response(status_code=200, content="ok")

    scope = {"type": "http", "method": "GET", "path": "/", "client": ("127.0.0.1", 12345), "headers": []}
    req = Request(scope)

    r1 = await middleware.dispatch(req, call_next)
    assert isinstance(r1, Response) and r1.status_code == 200
    r2 = await middleware.dispatch(req, call_next)
    assert r2.status_code == 200
    r3 = await middleware.dispatch(req, call_next)
    assert r3.status_code == 200


@pytest.mark.asyncio
async def test_requests_exceed_limit_blocked(monkeypatch):
    cfg = Config()
    cfg.LONG_POLLING_RATE_LIMIT_INTERVAL = 60
    cfg.LONG_POLLING_RATE_LIMIT_REQUESTS = 2

    middleware = RateLimitingMiddleware(DummyApp(), cfg)

    async def call_next(request):
        return Response(status_code=200, content="ok")

    scope = {"type": "http", "method": "GET", "path": "/", "client": ("10.0.0.1", 12345), "headers": []}
    req = Request(scope)

    r1 = await middleware.dispatch(req, call_next)
    assert r1.status_code == 200
    r2 = await middleware.dispatch(req, call_next)
    assert r2.status_code == 200
    r3 = await middleware.dispatch(req, call_next)
    assert r3.status_code == 429
    assert (await r3.body()) == b"Rate limit exceeded"


@pytest.mark.asyncio
async def test_old_timestamps_cleaned_then_allowed(monkeypatch):
    cfg = Config()
    cfg.LONG_POLLING_RATE_LIMIT_INTERVAL = 1
    cfg.LONG_POLLING_RATE_LIMIT_REQUESTS = 1

    middleware = RateLimitingMiddleware(DummyApp(), cfg)

    # Manually insert an old timestamp
    client_ip = "192.0.2.1"
    old_ts = time.time() - 10
    middleware._client_requests[client_ip].append(old_ts)

    async def call_next(request):
        return Response(status_code=200, content="ok")

    scope = {"type": "http", "method": "GET", "path": "/", "client": (client_ip, 12345), "headers": []}
    req = Request(scope)

    # Should be allowed since old timestamp is outside window
    r = await middleware.dispatch(req, call_next)
    assert r.status_code == 200
