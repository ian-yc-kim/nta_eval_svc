import logging
from typing import Generator

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy import create_engine

from nta_eval_svc.config import config as app_config

logger = logging.getLogger(__name__)


def _build_engine(database_url: str) -> Engine:
    """Create SQLAlchemy engine with appropriate pooling and connection args.

    Handles SQLite (in-memory and file-based) and general SQL dialects with
    connection pooling options sourced from configuration.
    """
    url = make_url(database_url)
    try:
        # Common options
        common_kwargs: dict = {
            "pool_pre_ping": True,
            "echo": app_config.DB_ECHO,
        }

        # Dialect specific handling
        if url.get_backend_name() == "sqlite":
            connect_args = {"check_same_thread": False}
            if url.database in (None, ":memory:"):
                # In-memory SQLite should use StaticPool so all connections
                # share the same in-memory DB for the life of the process.
                engine = create_engine(
                    database_url,
                    connect_args=connect_args,
                    poolclass=StaticPool,
                    **common_kwargs,
                )
            else:
                # File-based SQLite: allow multithread access
                engine = create_engine(
                    database_url,
                    connect_args=connect_args,
                    **common_kwargs,
                )
        else:
            # For other DBs (e.g., PostgreSQL) use QueuePool with configured sizing
            create_kwargs: dict = {
                **common_kwargs,
                "pool_size": app_config.DB_POOL_SIZE,
                "max_overflow": app_config.DB_MAX_OVERFLOW,
                "pool_timeout": app_config.DB_POOL_TIMEOUT,
                "pool_recycle": app_config.DB_POOL_RECYCLE,
            }
            connect_args: dict = {}
            if app_config.DB_SSL_MODE:
                # Many drivers use sslmode, but this is driver-dependent
                connect_args["sslmode"] = app_config.DB_SSL_MODE
            if connect_args:
                create_kwargs["connect_args"] = connect_args
            engine = create_engine(database_url, **create_kwargs)

        return engine
    except Exception as e:
        logger.error(e, exc_info=True)
        raise


# Module-level engine and Session factory
_engine: Engine = _build_engine(app_config.DATABASE_URL)
SessionLocal = sessionmaker(
    bind=_engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


def get_engine() -> Engine:
    """Return the process-wide SQLAlchemy engine instance."""
    return _engine


def dispose_engine() -> None:
    """Dispose of the engine's connection pool and reset connections."""
    try:
        _engine.dispose()
    except Exception as e:
        logger.error(e, exc_info=True)
        # do not re-raise to avoid crashing shutdown paths


def check_database_connection() -> bool:
    """Perform a simple health check against the database.

    Returns True if a connection can be established and a trivial query
    executes successfully; otherwise returns False and logs the error.
    """
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            # For engines that use transactional DDL/queries, commit if needed
            try:
                conn.commit()
            except Exception:
                # Some dialects (e.g., SQLite in autocommit) don't need explicit commit
                pass
        return True
    except SQLAlchemyError as e:
        logger.error(e, exc_info=True)
        return False
    except Exception as e:
        logger.error(e, exc_info=True)
        return False


def get_db() -> Generator[Session, None, None]:
    """FastAPI-friendly dependency that yields a DB session.

    Manages transaction lifecycle: commits on successful completion, rolls back
    on exception, and always closes the session.
    """
    session: Session = SessionLocal()
    try:
        try:
            yield session
            try:
                session.commit()
            except Exception as e:
                # If commit itself fails, ensure rollback and re-raise
                logger.error(e, exc_info=True)
                session.rollback()
                raise
        except Exception as e:
            logger.error(e, exc_info=True)
            session.rollback()
            raise
    finally:
        try:
            session.close()
        except Exception as e:
            logger.error(e, exc_info=True)
