"""`/role-groups/*` — Create New Role Group form (01d §2.4, R3-R4). Thin: services do the work."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_reader_db, get_writer_db
from app.core.security import Principal, get_current_principal
from app.schemas.common import ErrorResponse
from app.schemas.role_groups import CreateRoleGroupRequest, PermissionOption, RoleGroupCreated
from app.services import role_groups


router = APIRouter(prefix="/role-groups", tags=["Role groups"])

_ERRORS = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}


@router.get(
    "/permission-options",
    response_model=list[PermissionOption],
    responses=_ERRORS,
    summary="R3 Permissions the caller may assign",
)
async def permission_options(
    principal: Principal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_reader_db),
) -> list[PermissionOption]:
    return await role_groups.permission_options(db, principal)


@router.post(
    "",
    response_model=RoleGroupCreated,
    status_code=status.HTTP_201_CREATED,
    responses=_ERRORS,
    summary="R4 Create a role group",
)
async def create_role_group(
    body: CreateRoleGroupRequest,
    principal: Principal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_writer_db),
) -> RoleGroupCreated:
    return await role_groups.create_role_group(db, principal, body)
