"""
Central settings, loaded from environment variables / .env.

Segment map (so future segments know where things live):
  Segment 1 (this one): app scaffold, config, DB models, auth
  Segment 2: documents (upload, queue, get, list) + OCR engine adapters
  Segment 3: validation rules engine + review/correction endpoints
  Segment 4: admin (users, validation-rule config, OCR settings, CER
              benchmark) + reports/dashboard endpoints
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"

    database_url: str = "postgresql://postgres:YourStrongPassword@localhost:5432/waqf_docverify"

    jwt_secret_key: str = "insecure-dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 480

    # OCR engines
    sarvam_api_key: str | None = None
    sarvam_api_base_url: str = "https://api.sarvam.ai"

    gemini_api_key: str | None = None
    gemini_model: str = "gemini-flash-latest"  # alias Google keeps pointed at their current Flash model

    shasan_slm_api_url: str | None = None
    shasan_slm_api_key: str | None = None

    # AWS S3 (optional file storage)
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_s3_bucket: str | None = None
    aws_s3_region: str = "ap-south-1"

    cors_origins: str = "http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def s3_configured(self) -> bool:
        """True only when every S3 field looks like a real value, not a
        leftover placeholder. Falls back to local disk storage otherwise."""
        return bool(
            self.aws_access_key_id
            and self.aws_secret_access_key
            and self.aws_secret_access_key != "your_secret_key_here"
            and self.aws_s3_bucket
        )

    @property
    def sarvam_configured(self) -> bool:
        return bool(self.sarvam_api_key)

    @property
    def gemini_configured(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def shasan_configured(self) -> bool:
        return bool(self.shasan_slm_api_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()
