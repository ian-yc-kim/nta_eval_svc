build:
	poetry install

setup:
	poetry run alembic upgrade head

unittest:
	poetry run pytest tests

run:
	poetry run nta_eval_svc

celery_worker:
	celery -A nta_eval_svc.workers.celery_app worker --loglevel=info
