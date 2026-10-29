"""
Role groups (01d Â§2.4): the Create New Role Group form.

* R3 `GET /role-groups/permission-options` â€” the "Assign Roles To Group" tick-list =
  the **caller's own** permissions, role-table order.
* R4 `POST /role-groups` â€” legacy `RolesGroup/AddOrUpdateRolesGroup` (new), SuperAdmin area
  + "Add Role Group". Name required, â‰¤ 50, unique in the current site. UserType sets one of
  IsSiteAdmin / IsEndUser / IsSubDivision (Default = none). **F25 fix:** IsSuperAdmin and
  IsSystemAdmin are never set from the request, and every role id must be one the caller holds.

Current site: the legacy default (`UserContext.default_site_id`) until `X-Site-Id` (S2,
P1-M3) arrives.

Tables: R ApplicationRoles, ApplicationRoleGroups + the caller's context Â·
W ApplicationRoleGroups, ApplicationRolesInGroups (R4).
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.core.exceptions import CredentialsError, ForbiddenError
from app.core.legacy_time import india_now, new_legacy_guid
from app.core.security import Principal
from app.models.legacy import (
    ApplicationRole,
    ApplicationRoleGroup,
    ApplicationRoleInGroup,
    ApplicationUser,
)
from app.schemas.role_groups import (
    CreateRoleGroupRequest,
    PermissionOption,
    RoleGroupCreated,
    UserType,
)
from app.services.legacy_validation import FieldErrors
from app.services.user_context import UserContext, build_user_context


log = structlog.get_logger(__name__)

ADD_ROLE_GROUP = "Add Role Group"
NAME_TAKEN = "A role group with this name already exists in this site."


async def _super_admin_context(session: AsyncSession, principal: Principal) -> UserContext:
    """Legacy `CustomAuthorize(SuperAdmin = true)`; System Admin bypasses as everywhere (S4)."""
    user = await session.get(ApplicationUser, principal.user_id)
    if user is None:
        raise CredentialsError("Session ended. Please log in again.", error_code="SESSION_ENDED")
    ctx = await build_user_context(session, user)
    if not (ctx.flags.is_super_admin or ctx.flags.is_system_admin):
        raise ForbiddenError
    return ctx


async def _own_permissions(session: AsyncSession, ctx: UserContext) -> list[PermissionOption]:
    if not ctx.permissions:
        return []
    rows = await session.execute(
        select(ApplicationRole.id, ApplicationRole.name)
        .where(ApplicationRole.name.in_(ctx.permissions))
        .order_by(ApplicationRole.id)
    )
    return [PermissionOption(id=r.id, name=r.name) for r in rows]


async def permission_options(session: AsyncSession, principal: Principal) -> list[PermissionOption]:
    ctx = await _super_admin_context(session, principal)
    return await _own_permissions(session, ctx)


async def create_role_group(
    session: AsyncSession, principal: Principal, body: CreateRoleGroupRequest
) -> RoleGroupCreated:
    ctx = await _super_admin_context(session, principal)
    if ADD_ROLE_GROUP not in ctx.permissions and not ctx.flags.is_system_admin:
        raise ForbiddenError
    site_id = ctx.default_site_id
    if site_id is None:
        raise ForbiddenError("No site is assigned to this user.", error_code="NO_SITE_ASSIGNED")

    errors = FieldErrors()
    if errors.required("name", "Name", body.name):
        name = body.name or ""
        errors.max_length("name", "Name", name, 50)
        taken = await session.scalar(
            select(func.count())
            .select_from(ApplicationRoleGroup)
            .where(
                ApplicationRoleGroup.site_id == site_id,
                func.upper(ApplicationRoleGroup.name) == name.upper(),
            )
        )
        if taken:
            errors.add("name", NAME_TAKEN)
    errors.raise_if_any()

    role_ids = list(dict.fromkeys(body.role_ids))
    allowed = {p.id for p in await _own_permissions(session, ctx)}
    if not set(role_ids) <= allowed:
        raise ForbiddenError(
            "You can only assign permissions you hold.", error_code="PERMISSION_NOT_ALLOWED"
        )

    group = ApplicationRoleGroup(
        name=body.name,
        site_id=site_id,
        is_site_admin=body.user_type == UserType.SITE_ADMIN,
        is_end_user=body.user_type == UserType.END_USER,
        is_sub_division=body.user_type == UserType.SUB_DIVISION,
        is_super_admin=False,
        is_system_admin=False,
        is_editable=True,
        created_by_user_id=ctx.user.id,
        created_date=india_now(),
        guid=new_legacy_guid(),
    )
    session.add(group)
    await session.flush()
    session.add_all(
        ApplicationRoleInGroup(
            application_role_group_id=group.id, application_role_id=rid, guid=new_legacy_guid()
        )
        for rid in role_ids
    )
    await session.commit()
    log.info("role_group_created", group_id=group.id, site_id=site_id, roles=len(role_ids))
    return RoleGroupCreated(id=group.id, guid=group.guid)
