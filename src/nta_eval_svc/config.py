import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Application configuration loaded from environment variables.

    This class reads configuration from environment variables at instantiation
    time. It is intended to be used as a singleton via the module-level
    `config` instance defined below. New configuration fields should follow the
    existing patterns for consistency and safety.
    """

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

        # OpenAI configuration
        # Store raw API key; validation happens on access via property.
        self._OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY") or None
        # Model defaults to "gpt-3.5-turbo"; blank env values fall back to default.
        self.OPENAI_MODEL: str = (os.getenv("OPENAI_MODEL") or "gpt-3.5-turbo").strip() or "gpt-3.5-turbo"

        # Redis and Celery configuration defaults
        # Redis host/port used as convenient defaults for Celery broker/result backend
        self.REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
        self.REDIS_PORT: int = self._get_int("REDIS_PORT", 6379)

        # Celery connection URLs: explicit env vars take precedence; otherwise derive from REDIS_*
        self.CELERY_BROKER_URL: str = os.getenv(
            "CELERY_BROKER_URL",
            f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/0"
        )
        self.CELERY_RESULT_BACKEND: str = os.getenv(
            "CELERY_RESULT_BACKEND",
            f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/0"
        )

        # Serializers and accepted content
        self.CELERY_TASK_SERIALIZER: str = os.getenv("CELERY_TASK_SERIALIZER", "json")
        self.CELERY_RESULT_SERIALIZER: str = os.getenv("CELERY_RESULT_SERIALIZER", "json")
        self.CELERY_ACCEPT_CONTENT: str = os.getenv("CELERY_ACCEPT_CONTENT", "json")

        # Timezone and UTC handling
        self.CELERY_TIMEZONE: str = os.getenv("CELERY_TIMEZONE", "UTC")
        self.CELERY_ENABLE_UTC: bool = self._get_bool("CELERY_ENABLE_UTC", True)

        # Task tracking and concurrency
        self.CELERY_TASK_TRACK_STARTED: bool = self._get_bool("CELERY_TASK_TRACK_STARTED", True)
        self.CELERY_WORKER_CONCURRENCY: int = self._get_int("CELERY_WORKER_CONCURRENCY", 4)

        # Long polling configuration
        # Default timeout in seconds for a long-polling request
        self.LONG_POLLING_DEFAULT_TIMEOUT: int = self._get_int("LONG_POLLING_DEFAULT_TIMEOUT", 30)
        # Poll interval in seconds (float) used for asyncio.sleep when polling
        self.LONG_POLLING_POLL_INTERVAL: float = self._get_float("LONG_POLLING_POLL_INTERVAL", 0.5)
        # Connection limits
        self.LONG_POLLING_MAX_CLIENT_CONNECTIONS: int = self._get_int("LONG_POLLING_MAX_CLIENT_CONNECTIONS", 5)
        self.LONG_POLLING_GLOBAL_MAX_CONNECTIONS: int = self._get_int("LONG_POLLING_GLOBAL_MAX_CONNECTIONS", 1000)
        # Rate limiting window and request limit
        self.LONG_POLLING_RATE_LIMIT_INTERVAL: int = self._get_int("LONG_POLLING_RATE_LIMIT_INTERVAL", 60)
        self.LONG_POLLING_RATE_LIMIT_REQUESTS: int = self._get_int("LONG_POLLING_RATE_LIMIT_REQUESTS", 100)

    @property
    def OPENAI_API_KEY(self) -> str:
        """Validated OpenAI API key.

        Returns:
            str: The configured API key.

        Raises:
            ValueError: If the API key is not configured or is blank.
        """
        val = self._OPENAI_API_KEY
        if val is None or val.strip() == "":
            raise ValueError(
                "OPENAI_API_KEY is not configured. Set the OPENAI_API_KEY environment variable."
            )
        return val

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

    @staticmethod
    def _get_float(key: str, default: float) -> float:
        """Read environment variable as float with safe fallback to default."""
        val = os.getenv(key)
        if val is None:
            return default
        try:
            return float(val)
        except (ValueError, TypeError):
            return default


# Singleton config instance
config = Config()

# Backward-compatible module-level constants
DATABASE_URL = config.DATABASE_URL
SERVICE_PORT = config.SERVICE_PORT
