# nta_eval_svc

Quickstart: Redis and Celery

This service uses Redis as the Celery broker and result backend. The Makefile includes a target to run a Celery worker.

Install Redis locally

- macOS (Homebrew):
  - brew install redis
  - brew services start redis
  - or run redis-server directly: redis-server

- Ubuntu / Debian:
  - sudo apt-get update && sudo apt-get install -y redis-server
  - sudo systemctl enable --now redis

Verify Redis is running

- redis-cli ping
- expected output: PONG

Environment variables

- REDIS_HOST: hostname serving Redis (default: localhost)
- REDIS_PORT: Redis port (default: 6379)
- You can set them like:

  export REDIS_HOST=127.0.0.1
  export REDIS_PORT=6379

Celery broker/result configuration can also be provided directly via:

  export CELERY_BROKER_URL=redis://${REDIS_HOST}:${REDIS_PORT}/0
  export CELERY_RESULT_BACKEND=redis://${REDIS_HOST}:${REDIS_PORT}/0

Run the service and worker

1. Install Python dependencies:
   make build

2. Start Redis (see instructions above)

3. Start the FastAPI service:
   make run

4. Start a Celery worker using Makefile target:
   make celery_worker

Notes

- The Celery app is defined at nta_eval_svc.workers.celery_app.
- If Redis is not running on localhost, set REDIS_HOST and REDIS_PORT environment variables before starting the worker or the service.
- Integration tests mock Celery calls and do not require a running Redis instance.
