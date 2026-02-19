import os
from functools import lru_cache

from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError


load_dotenv()


class Settings(BaseModel):
    jira_base_url: str
    jira_email: str
    jira_api_token: str
    request_connect_timeout_seconds: float = Field(default=5.0, gt=0)
    request_read_timeout_seconds: float = Field(default=20.0, gt=0)
    retry_max_attempts: int = Field(default=3, ge=1, le=8)
    retry_backoff_seconds: float = Field(default=0.5, ge=0)
    enable_response_cache: bool = True
    cache_ttl_seconds: int = Field(default=180, ge=120, le=300)
    log_level: str = "INFO"

    @property
    def request_timeout(self) -> tuple[float, float]:
        return (self.request_connect_timeout_seconds, self.request_read_timeout_seconds)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load and validate application settings from environment variables."""
    try:
        settings = Settings(
            jira_base_url=(os.getenv("JIRA_BASE_URL") or "").rstrip("/"),
            jira_email=os.getenv("JIRA_EMAIL") or "",
            jira_api_token=os.getenv("JIRA_API_TOKEN") or "",
            request_connect_timeout_seconds=float(
                os.getenv("REQUEST_CONNECT_TIMEOUT_SECONDS") or 5.0
            ),
            request_read_timeout_seconds=float(
                os.getenv("REQUEST_READ_TIMEOUT_SECONDS") or 20.0
            ),
            retry_max_attempts=int(os.getenv("RETRY_MAX_ATTEMPTS") or 3),
            retry_backoff_seconds=float(os.getenv("RETRY_BACKOFF_SECONDS") or 0.5),
            enable_response_cache=(
                os.getenv("ENABLE_RESPONSE_CACHE", "true").strip().lower() == "true"
            ),
            cache_ttl_seconds=int(os.getenv("CACHE_TTL_SECONDS") or 180),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )
    except (ValidationError, ValueError) as exc:
        raise RuntimeError(f"Invalid Jira configuration: {exc}") from exc

    missing = [
        key
        for key, value in {
            "JIRA_BASE_URL": settings.jira_base_url,
            "JIRA_EMAIL": settings.jira_email,
            "JIRA_API_TOKEN": settings.jira_api_token,
        }.items()
        if not value
    ]

    if missing:
        raise RuntimeError(
            "Missing required environment variables: " + ", ".join(missing)
        )

    return settings
