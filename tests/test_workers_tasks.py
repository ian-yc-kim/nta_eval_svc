import importlib
import os
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select


def _reload_config_and_db(monkeypatch, db_url: str):
    # Set env and reload modules that read env at import time
    monkeypatch.setenv("DATABASE_URL", db_url)
    import nta_eval_svc.config as cfg
    importlib.reload(cfg)
    import nta_eval_svc.core.database as db
    importlib.reload(db)
    return cfg, db


def test_process_evaluation_job_success(monkeypatch, tmp_path):
    # Create a file SQLite DB to share between task and test
    db_file = tmp_path / "test_worker.db"
    db_url = f"sqlite:///{db_file}"

    cfg, db = _reload_config_and_db(monkeypatch, db_url)

    # Build engine and create tables
    engine = db._build_engine(db_url)
    from nta_eval_svc.models.base import Base

    Base.metadata.create_all(engine)

    # Insert criteria and job
    Session = sessionmaker(bind=engine)
    s = Session()
    from nta_eval_svc.models.evaluation import EvaluationCriteria, EvaluationJob

    crit = EvaluationCriteria(agent_name="a1", version=1, criteria_yaml="x:1")
    s.add(crit)
    s.commit()
    s.refresh(crit)

    job = EvaluationJob(
        evaluation_id=crit.id,
        agent_name=crit.agent_name,
        version=crit.version,
        prompt="do it",
        status="pending",
    )
    s.add(job)
    s.commit()
    s.refresh(job)
    job_id = job.id
    s.close()

    # Reload celery app and tasks so they pick up updated config
    import nta_eval_svc.workers.celery_app as celery_mod
    importlib.reload(celery_mod)
    import nta_eval_svc.workers.tasks as tasks_mod
    importlib.reload(tasks_mod)

    # Run tasks eagerly
    celery_mod.celery_app.conf.task_always_eager = True
    celery_mod.celery_app.conf.task_eager_propagates = True

    # Execute the task
    res = tasks_mod.process_evaluation_job.apply(args=[job_id])

    # Check DB for completed status
    Session2 = sessionmaker(bind=engine)
    s2 = Session2()
    j = s2.execute(select(EvaluationJob).where(EvaluationJob.id == job_id)).scalars().one()
    assert j.status == "completed"
    assert j.completed_at is not None
    s2.close()


def test_process_evaluation_job_failure_sets_failed(monkeypatch, tmp_path):
    db_file = tmp_path / "test_worker2.db"
    db_url = f"sqlite:///{db_file}"

    cfg, db = _reload_config_and_db(monkeypatch, db_url)

    engine = db._build_engine(db_url)
    from nta_eval_svc.models.base import Base

    Base.metadata.create_all(engine)

    Session = sessionmaker(bind=engine)
    s = Session()
    from nta_eval_svc.models.evaluation import EvaluationCriteria, EvaluationJob

    crit = EvaluationCriteria(agent_name="a2", version=1, criteria_yaml="y:2")
    s.add(crit)
    s.commit()
    s.refresh(crit)

    job = EvaluationJob(
        evaluation_id=crit.id,
        agent_name=crit.agent_name,
        version=crit.version,
        prompt="fail",
        status="pending",
    )
    s.add(job)
    s.commit()
    s.refresh(job)
    job_id = job.id
    s.close()

    # Reload celery app and tasks so they pick up updated config
    import nta_eval_svc.workers.celery_app as celery_mod
    importlib.reload(celery_mod)
    import nta_eval_svc.workers.tasks as tasks_mod
    importlib.reload(tasks_mod)

    # Run tasks eagerly
    celery_mod.celery_app.conf.task_always_eager = True
    celery_mod.celery_app.conf.task_eager_propagates = True

    # Force processing to raise by monkeypatching time.sleep used in task
    import nta_eval_svc.workers.tasks as tmod
    monkeypatch.setattr(tmod, "time", type("T", (), {"sleep": lambda *_: (_ for _ in ()).throw(RuntimeError("boom"))}))

    # Disable retries for deterministic test
    setattr(tmod.process_evaluation_job, "max_retries", 0)

    # Execute the task (should not raise since task handles exception path)
    res = tmod.process_evaluation_job.apply(args=[job_id])

    # Check DB for failed status
    Session2 = sessionmaker(bind=engine)
    s2 = Session2()
    j = s2.execute(select(EvaluationJob).where(EvaluationJob.id == job_id)).scalars().one()
    assert j.status == "failed"
    assert j.error_message is not None and "boom" in j.error_message
    s2.close()
