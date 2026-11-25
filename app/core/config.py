"""Application settings loaded from environment variables / .env file."""

from functools import lru_cache
from typing import Annotated, Literal
from urllib.parse import quote_plus

from pydantic import Field, SecretStr, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["local", "test", "staging", "production"]

_INSECURE_SECRET = "change-me-in-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ---
    APP_NAME: str = "TaskFlow API"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: Environment = "local"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"
    DOCS_ENABLED: bool = True

    # --- Logging ---
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = True

    # --- Security ---
    SECRET_KEY: SecretStr = SecretStr(_INSECURE_SECRET)
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30, gt=0)
    REFRESH_TOKEN_EXPIRE_MINUTES: int = Field(default=60 * 24 * 7, gt=0)
    BCRYPT_ROUNDS: int = Field(default=12, ge=4, le=31)
    CORS_ORIGINS: Annotated[list[str], NoDecode] = []

    # --- Database ---
    MYSQL_HOST: str = "localhost"
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = "taskflow"
    MYSQL_PASSWORD: SecretStr = SecretStr("taskflow")
    MYSQL_DB: str = "taskflow"
    # Full override, e.g. for tests: sqlite+aiosqlite:///./test.db
    DATABASE_URL_OVERRIDE: str | None = None

    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_RECYCLE_SECONDS: int = 1800
    DB_POOL_TIMEOUT_SECONDS: int = 30
    DB_ECHO: bool = False

    # --- Pagination ---
    DEFAULT_PAGE_SIZE: int = 20
    MAX_PAGE_SIZE: int = 100

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _split_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @model_validator(mode="after")
    def _validate_production_safety(self) -> "Settings":
        if self.ENVIRONMENT == "production":
            if self.SECRET_KEY.get_secret_value() == _INSECURE_SECRET:
                raise ValueError("SECRET_KEY must be set to a secure value in production")
            if len(self.SECRET_KEY.get_secret_value()) < 32:
                raise ValueError("SECRET_KEY must be at least 32 characters in production")
            if self.DEBUG:
                raise ValueError("DEBUG must be disabled in production")
            if self.BCRYPT_ROUNDS < 12:
                raise ValueError("BCRYPT_ROUNDS must be at least 12 in production")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def DATABASE_URL(self) -> str:  # noqa: N802
        if self.DATABASE_URL_OVERRIDE:
            return self.DATABASE_URL_OVERRIDE
        password = quote_plus(self.MYSQL_PASSWORD.get_secret_value())
        return (
            f"mysql+aiomysql://{self.MYSQL_USER}:{password}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DB}?charset=utf8mb4"
        )

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
