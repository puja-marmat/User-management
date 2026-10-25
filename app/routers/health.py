"""
Health endpoints (no auth).

GET /health        liveness: process is up; never touches the database.
GET /health/ready  readiness: one round-trip to SQL Server (`sav_uat`).
                   Outside prod the body also reports SQL Server version, compatibility
                   level, whether the `iam` schema exists and whether Change Tracking is on
                   (inputs needed for M1). In prod only the status is returned.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.core.config import get_settings
from app.core.database import get_reader_db
from app.core.exceptions import ServiceUnavailableError
from app.schemas.common import CamelModel
from app.services.health_service import probe_database


router = APIRouter(prefix="/health", tags=["health"])
log = structlog.get_logger(__name__)


class LiveResponse(CamelModel):
    status: str
    service: str
    version: str
    environment: str


class DatabaseInfo(CamelModel):
    name: str
    product_version: str
    major_version: str
    edition: str
    compatibility_level: int | None
    iam_schema_exists: bool
    change_tracking_enabled: bool


class ReadyResponse(CamelModel):
    status: str
    database: DatabaseInfo | None = None


@router.get("", response_model=LiveResponse, response_model_by_alias=True)
async def live() -> LiveResponse:
    s = get_settings()
    return LiveResponse(
        status="ok", service=s.APP_NAME, version=s.APP_VERSION, environment=s.ENVIRONMENT
    )


@router.get(
    "/ready",
    response_model=ReadyResponse,
    response_model_by_alias=True,
    response_model_exclude_none=True,
    responses={503: {"description": "Database not reachable"}},
)
async def ready(db: AsyncSession = Depends(get_reader_db)) -> ReadyResponse:
    try:
        st = await probe_database(db)
    except Exception as exc:
        # Log the exception type only: driver messages can echo server/login names.
        log.warning("readiness_failed", exc_type=type(exc).__name__)
        raise ServiceUnavailableError(
            "Database not reachable", error_code="DB_UNAVAILABLE"
        ) from exc

    if get_settings().is_production:
        return ReadyResponse(status="ready")
    return ReadyResponse(
        status="ready",
        database=DatabaseInfo(
            name=st.database_name,
            product_version=st.product_version,
            major_version=st.major_version,
            edition=st.edition,
            compatibility_level=st.compatibility_level,
            iam_schema_exists=st.iam_schema_exists,
            change_tracking_enabled=st.change_tracking_enabled,
        ),
    )
