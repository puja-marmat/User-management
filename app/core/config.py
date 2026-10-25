"""
Application settings (12-factor: everything from environment / `.env`).

Database URLs (plan §4.1, DEC-32):
    DB_WRITER_URL     required — read/write engine used by the API.
    DB_READER_URL     optional — defaults to DB_WRITER_URL.
    DB_MIGRATION_URL  optional — used by Alembic and the migration CLI; defaults to DB_WRITER_URL.

Phase 1 uses one SQL Server login for all three. They stay separate settings so the
later split into iam_migrator / iam_app / iam_projector needs no code change.

Phase 1 (U01 plan DEC-43): **only `sav_uat` is connected**. There is deliberately no
MasterDb / Audit DB URL setting; MasterDb routing goes to a local CSV file (DEC-44).

Never log, print or return these URLs: they contain credentials.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


Environment = Literal["local", "dev", "uat", "prod", "test"]
MasterDbMode = Literal["off", "file", "live"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    # ── Service ──────────────────────────────────────────────────────────────
    APP_NAME: str = "prime-mdm-backend"
    APP_VERSION: str = "0.1.0"
    ENVIRONMENT: Environment = "local"
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = True

    # ── Database (SQL Server, sav_uat) ───────────────────────────────────────
    DB_WRITER_URL: SecretStr | None = None
    DB_READER_URL: SecretStr | None = None
    DB_MIGRATION_URL: SecretStr | None = None
    DB_POOL_SIZE: int = Field(default=5, ge=1, le=50)
    DB_MAX_OVERFLOW: int = Field(default=10, ge=0, le=100)
    DB_POOL_RECYCLE_SECONDS: int = Field(default=1800, ge=60)
    DB_ECHO: bool = False
    DB_HEALTH_TIMEOUT_SECONDS: float = Field(default=5.0, gt=0)

    # ── Phase 1 migration guard (00a §0.1) ───────────────────────────────────
    # Alembic is dormant in Phase 1: every online Alembic command and the container
    # `migrate` mode refuse to run unless this is explicitly true (Phase 2 / CI scratch DB).
    IAM_MIGRATIONS_ENABLED: bool = False

    # ── MasterDb routing (U01 DEC-44; legacy UserController.CreateUserInMasterDb) ──
    # off  = no routing-store operation
    # file = legacy logic, rows kept in a local CSV file (Phase 1)
    # live = reserved for a future, approved MasterDb integration (refuses to start)
    MASTERDB_MODE: MasterDbMode = "file"
    MASTERDB_FILE_PATH: Path = Path("data/masterdb-routing.csv")
    MASTERDB_LOCK_TIMEOUT_SECONDS: float = Field(default=10.0, gt=0)
    # Non-secret values of the UAT cp-web appSettings (legacy key in brackets).
    # Kept raw on purpose: legacy treats a missing key (null) and an empty value ("")
    # differently (see app/services/masterdb_routing.py), so empty strings are NOT
    # turned into None here.
    MASTERDB_API_BASE_URL: str | None = None  # [ApiBaseurl]
    MASTERDB_PAYMENT_URL: str | None = None  # [PaymentUrl]
    PAYU_SITE_IDS: str | None = None  # [PayUSiteId] comma/semicolon list, parsed like legacy

    # ── Parity tool (app/parity) ─────────────────────────────────────────────
    # Key for HMAC-hashing personal fields in snapshots; local value, never logged.
    PARITY_HASH_KEY: SecretStr | None = None

    # ── Authentication (P1-M2, U01 01d A1-A10; decisions D1/D4 of 01d) ──────────
    # Access tokens: RS256 JWT, private key as PEM. Required outside local/test; in
    # local/test an ephemeral key is generated at start-up (tokens die on restart).
    JWT_PRIVATE_KEY_PEM: SecretStr | None = None
    JWT_ISSUER: str = "prime-mdm-backend"
    JWT_AUDIENCE: str = "prime-mdm"
    ACCESS_TOKEN_MINUTES: int = Field(default=30, ge=1, le=120)  # = legacy stamp re-check
    REFRESH_TOKEN_DAYS: int = Field(default=14, ge=1, le=60)  # = OWIN default, sliding
    # Forgot-password OTP challenge and reset ticket (HMAC key; F1 fix). Same rule as above.
    OTP_SIGNING_KEY: SecretStr | None = None
    OTP_TTL_MINUTES: int = Field(default=10, ge=1, le=1440)
    RESET_TICKET_TTL_MINUTES: int = Field(default=10, ge=1, le=1440)
    # Sender of queued alerts (legacy appSetting [CustomerSupportEmail]); AlertQueues.FromAddress
    # is NOT NULL, so alerts are skipped (and logged) when this is missing.
    ALERT_FROM_ADDRESS: str | None = None

    # ── HTTP ─────────────────────────────────────────────────────────────────
    CORS_ORIGINS: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    @field_validator(
        "DB_WRITER_URL",
        "DB_READER_URL",
        "DB_MIGRATION_URL",
        "PARITY_HASH_KEY",
        "JWT_PRIVATE_KEY_PEM",
        "OTP_SIGNING_KEY",
        "ALERT_FROM_ADDRESS",
        mode="before",
    )
    @classmethod
    def _empty_is_none(cls, v: object) -> object:
        return None if isinstance(v, str) and not v.strip() else v

    @field_validator("IAM_MIGRATIONS_ENABLED", mode="before")
    @classmethod
    def _empty_is_false(cls, v: object) -> object:
        return False if isinstance(v, str) and not v.strip() else v

    # ── Derived ──────────────────────────────────────────────────────────────
    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "prod"

    @property
    def allows_ephemeral_keys(self) -> bool:
        """Only local development and tests may run with generated signing keys."""
        return self.ENVIRONMENT in ("local", "test")

    @property
    def writer_url(self) -> str:
        if self.DB_WRITER_URL is None:
            raise RuntimeError("DB_WRITER_URL is not set (see .env.example)")
        return self.DB_WRITER_URL.get_secret_value()

    @property
    def reader_url(self) -> str:
        return self.DB_READER_URL.get_secret_value() if self.DB_READER_URL else self.writer_url

    @property
    def migration_url(self) -> str:
        return (
            self.DB_MIGRATION_URL.get_secret_value() if self.DB_MIGRATION_URL else self.writer_url
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


def validate_phase1_config(settings: Settings) -> None:
    """Fail fast on settings that Phase 1 does not allow (any environment)."""
    if settings.MASTERDB_MODE == "live":
        raise RuntimeError(
            "MASTERDB_MODE=live is not available in Phase 1 (U01 DEC-43/44): "
            "MasterDb is not connected. Use 'file' or 'off'."
        )


def validate_auth_config(settings: Settings) -> None:
    """Signing keys must be configured everywhere except local/test."""
    _check_otp_key_length(settings)
    if settings.allows_ephemeral_keys:
        return
    missing = [
        name
        for name in ("JWT_PRIVATE_KEY_PEM", "OTP_SIGNING_KEY")
        if getattr(settings, name) is None
    ]
    if missing:
        raise RuntimeError(
            f"{', '.join(missing)} must be set when ENVIRONMENT={settings.ENVIRONMENT}"
        )


def _check_otp_key_length(settings: Settings) -> None:
    key = settings.OTP_SIGNING_KEY
    if key is not None and len(key.get_secret_value().encode("utf-8")) < 32:
        raise RuntimeError("OTP_SIGNING_KEY must be at least 32 bytes long")


def validate_production_config(settings: Settings) -> None:
    """Fail fast at start-up on unsafe production configuration."""
    if not settings.is_production:
        return
    problems: list[str] = []
    if settings.DB_WRITER_URL is None:
        problems.append("DB_WRITER_URL missing")
    if settings.DB_ECHO:
        problems.append("DB_ECHO must be false in prod (would log SQL parameters)")
    if any(o == "*" for o in settings.CORS_ORIGINS):
        problems.append("CORS_ORIGINS must not contain '*'")
    if settings.IAM_MIGRATIONS_ENABLED:
        problems.append("IAM_MIGRATIONS_ENABLED must be false in Phase 1")
    if problems:
        raise RuntimeError("Unsafe production configuration: " + "; ".join(problems))
