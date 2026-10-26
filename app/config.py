from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CHECKIT_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )
    database_url: SecretStr = SecretStr("")
    admin_database_url: SecretStr = SecretStr("")
    backend_password: SecretStr = SecretStr("")
    environment: str = "development"
    cookie_secure: bool = False
    allowed_origins: list[str] = ["http://127.0.0.1:8000", "http://localhost:8000"]
    csrf_secret: SecretStr = SecretStr("")
    session_seconds: int = Field(default=604800, ge=300, le=2592000)
    smtp_host: str = ""
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_from: str = ""
    verification_page_url: str = ""

    @model_validator(mode="after")
    def validate_production(self):
        if self.environment not in {"development", "production"}:
            raise ValueError("environment must be development or production")
        if self.environment == "production" and (
            not self.cookie_secure or not self.allowed_origins
            or any(not origin.startswith("https://") for origin in self.allowed_origins)
            or len(self.csrf_secret.get_secret_value()) < 32
        ):
            raise ValueError("production requires HTTPS cookies, explicit HTTPS origins and a CSRF secret")
        return self
