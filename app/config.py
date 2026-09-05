"""Application configuration and environment settings."""

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    DATABASE_URL: str = "sqlite:///./mandate_mesh.db"
    DATABASE_URL_SYNC: str = "sqlite:///./mandate_mesh.db"

    # Environment & Identity
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"
    PLATFORM_KEY_ID: str = "platform:key-1"

    # Gemini / Google LLM Configuration
    GEMINI_API_KEY: str | None = None
    GOOGLE_API_KEY: str | None = None

    # Razorpay Gateway
    RAZORPAY_KEY_ID: str = "rzp_test_placeholder"
    RAZORPAY_KEY_SECRET: str = "rzp_secret_placeholder"
    RAZORPAY_WEBHOOK_SECRET: str = "rzp_webhook_secret_placeholder"

    @model_validator(mode="after")
    def sync_database_urls(self) -> "Settings":
        # Fall back DATABASE_URL_SYNC to DATABASE_URL if it was left as default sqlite
        if self.DATABASE_URL != "sqlite:///./mandate_mesh.db" and self.DATABASE_URL_SYNC == "sqlite:///./mandate_mesh.db":
            self.DATABASE_URL_SYNC = self.DATABASE_URL

        # SQLAlchemy requires postgresql:// rather than legacy postgres://
        if self.DATABASE_URL.startswith("postgres://"):
            self.DATABASE_URL = self.DATABASE_URL.replace("postgres://", "postgresql://", 1)
        if self.DATABASE_URL_SYNC.startswith("postgres://"):
            self.DATABASE_URL_SYNC = self.DATABASE_URL_SYNC.replace("postgres://", "postgresql://", 1)

        return self


settings = Settings()
