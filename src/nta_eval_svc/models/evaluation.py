from __future__ import annotations

import logging
import uuid
from typing import Optional

from sqlalchemy import (
    String,
    Integer,
    Text,
    DateTime,
    ForeignKey,
    Index,
    UniqueConstraint,
    CheckConstraint,
    func,
    JSON,
)
from sqlalchemy.orm import relationship, Mapped, mapped_column

from .base import Base


logger = logging.getLogger(__name__)


# Cross-DB UUID handling: use 36-char string with uuid4 default

def _uuid_str() -> str:
    try:
        return str(uuid.uuid4())
    except Exception as e:  # pragma: no cover
        logging.error(e, exc_info=True)
        # Fallback to a random-like string if uuid fails
        return uuid.uuid4().hex


class EvaluationCriteria(Base):
    __tablename__ = "evaluation_criteria"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    agent_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    criteria_yaml: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[Optional[str]] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("agent_name", "version", name="uq_criteria_agent_version"),
    )

    # Relationships
    evaluation_jobs: Mapped[list["EvaluationJob"]] = relationship(
        "EvaluationJob",
        back_populates="criteria",
        cascade="all, delete-orphan",
        passive_deletes=False,  # ensure ORM-level cascade delete even if DB FK cascade is not enforced (e.g., SQLite without PRAGMA)
    )


class EvaluationJob(Base):
    __tablename__ = "evaluation_job"

    STATUS_ENUM = ("pending", "in_progress", "completed", "failed")

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)

    evaluation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("evaluation_criteria.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    agent_name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    output: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Use String with an explicit CHECK constraint for robust cross-DB enforcement
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default="pending",
    )

    results: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[Optional[str]] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[Optional[str]] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    completed_at: Mapped[Optional[str]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_evaluation_job_agent_version", "agent_name", "version"),
        Index("ix_evaluation_job_status", "status"),
        CheckConstraint(
            "status IN ('pending','in_progress','completed','failed')",
            name="ck_evaluation_job_status",
        ),
    )

    # Relationships
    criteria: Mapped[EvaluationCriteria] = relationship(
        "EvaluationCriteria", back_populates="evaluation_jobs"
    )
