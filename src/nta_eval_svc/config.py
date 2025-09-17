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


# Singleton config instance
config = Config()

# Backward-compatible module-level constants
DATABASE_URL = config.DATABASE_URL
SERVICE_PORT = config.SERVICE_PORT
