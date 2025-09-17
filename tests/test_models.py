import logging
import uuid
from datetime import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from nta_eval_svc.models import Base
from nta_eval_svc.models.evaluation import EvaluationCriteria, EvaluationJob


logger = logging.getLogger(__name__)


def create_criteria(db_session, agent_name: str = "agentA", version: int = 1, yaml: str = "a: 1") -> EvaluationCriteria:
    crit = EvaluationCriteria(agent_name=agent_name, version=version, criteria_yaml=yaml)
    db_session.add(crit)
    db_session.commit()
    db_session.refresh(crit)
    return crit


def test_models_importable():
    # Simple import tests
    assert EvaluationCriteria.__tablename__ == "evaluation_criteria"
    assert EvaluationJob.__tablename__ == "evaluation_job"


def test_create_criteria_and_unique_constraint(db_session):
    c1 = create_criteria(db_session, agent_name="agentX", version=1)
    assert c1.id and len(c1.id) in (32, 36)
    assert c1.created_at is not None

    # Duplicate (agent_name, version) should fail
    with pytest.raises(IntegrityError):
        dup = EvaluationCriteria(agent_name="agentX", version=1, criteria_yaml="b: 2")
        db_session.add(dup)
        db_session.commit()
    db_session.rollback()


def test_fk_relationship_and_indices(db_session):
    crit = create_criteria(db_session, agent_name="agentRel", version=2)

    job = EvaluationJob(
        evaluation_id=crit.id,
        agent_name=crit.agent_name,
        version=crit.version,
        prompt="Evaluate this",
        status="pending",
    )
    db_session.add(job)
    db_session.commit()

    # Relationship check
    db_session.refresh(job)
    assert job.criteria.id == crit.id
    assert len(crit.evaluation_jobs) == 1

    # Indexed select on evaluation_id
    res = db_session.execute(select(EvaluationJob).where(EvaluationJob.evaluation_id == crit.id)).scalars().all()
    assert len(res) == 1


@pytest.mark.parametrize("status", ["pending", "in_progress", "completed", "failed"])
def test_enum_status_valid(db_session, status):
    crit = create_criteria(db_session, "agentStatus", 3)
    job = EvaluationJob(
        evaluation_id=crit.id,
        agent_name=crit.agent_name,
        version=crit.version,
        prompt="p",
        status=status,
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    assert job.status == status


def test_enum_status_invalid(db_session):
    crit = create_criteria(db_session, "agentBad", 4)
    bad = EvaluationJob(
        evaluation_id=crit.id,
        agent_name=crit.agent_name,
        version=crit.version,
        prompt="p",
        status="unknown",
    )
    db_session.add(bad)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_json_and_timestamps(db_session):
    crit = create_criteria(db_session, "agentJson", 5)
    job = EvaluationJob(
        evaluation_id=crit.id,
        agent_name=crit.agent_name,
        version=crit.version,
        prompt="json",
        results={"score": 0.95, "details": {"k": "v"}},
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    assert isinstance(job.created_at, datetime)
    assert isinstance(job.updated_at, datetime)
    assert job.results["score"] == 0.95

    # Trigger update for updated_at
    job.output = "done"
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    assert isinstance(job.updated_at, datetime)


def test_composite_index_agent_version_query(db_session):
    crit = create_criteria(db_session, "agentIdx", 7)
    job = EvaluationJob(
        evaluation_id=crit.id,
        agent_name="agentIdx",
        version=7,
        prompt="idx",
    )
    db_session.add(job)
    db_session.commit()

    rows = db_session.execute(
        select(EvaluationJob).where(
            EvaluationJob.agent_name == "agentIdx",
            EvaluationJob.version == 7,
        )
    ).scalars().all()
    assert len(rows) == 1


def test_cascade_delete(db_session):
    crit = create_criteria(db_session, "agentDel", 8)
    job = EvaluationJob(
        evaluation_id=crit.id,
        agent_name=crit.agent_name,
        version=crit.version,
        prompt="del",
    )
    db_session.add(job)
    db_session.commit()

    # Delete criteria should remove job via cascade
    db_session.delete(crit)
    db_session.commit()

    remaining = db_session.execute(select(EvaluationJob)).scalars().all()
    assert len(remaining) == 0
