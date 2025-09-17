import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Application configuration loaded from environment variables."""

    def __init__(self) -> None:
        # Core DB URL
        self.DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///:memory:")
        # Pooling and engine behavior
        self.DB_POOL_SIZE: int = self._get_int("DB_POOL_SIZE", 5)
        self.DB_MAX_OVERFLOW: int = self._get_int("DB_MAX_OVERFLOW", 10)
        self.DB_POOL_TIMEOUT: int = self._get_int("DB_POOL_TIMEOUT", 30)
        self.DB_POOL_RECYCLE: int = self._get_int("DB_POOL_RECYCLE", 1800)
        self.DB_ECHO: bool = self._get_bool("DB_ECHO", False)
        self.DB_SSL_MODE: str | None = os.getenv("DB_SSL_MODE") or None
        # Environment
        self.APP_ENV: str = os.getenv("APP_ENV", "development")
        # Service settings
        self.SERVICE_PORT: int = self._get_int("SERVICE_PORT", 8000)

    @staticmethod
    def _get_bool(key: str, default: bool) -> bool:
        val = os.getenv(key)
        if val is None:
            return default
        return val.strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _get_int(key: str, default: int) -> int:
        val = os.getenv(key)
        if val is None:
            return default
        try:
            return int(val)
        except ValueError:
            return default


# Singleton config instance
config = Config()

# Backward-compatible module-level constants
DATABASE_URL = config.DATABASE_URL
SERVICE_PORT = config.SERVICE_PORT
