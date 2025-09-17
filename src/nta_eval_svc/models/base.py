from sqlalchemy.orm import declarative_base

# Keep Base here for Alembic integration and metadata access
Base = declarative_base()

# Re-export the database dependency for FastAPI DI
from nta_eval_svc.core.database import get_db  # noqa: E402
