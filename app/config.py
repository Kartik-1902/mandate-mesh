"""Application configuration and environment settings."""

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


settings = Settings()
