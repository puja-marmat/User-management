"""
Who the signed-in user is: the equivalent of the legacy claims
[Code `CrystalPower.Infrastructure/Entities/Application/ApplicationUser.cs`
`GenerateUserIdentityAsync`] plus the default current site
[Code `CrystalPower.Web/Helpers/SiteHelpers/Functions.cs` `GetSiteIdOfLoginUser`].

* Permissions (`UserInRoles`): names of the roles in all of the user's role groups,
  role-table order [Inferred: `GetAll()` order = Id].
* Flags: any of the user's role groups has IsSuperAdmin / IsEndUser / IsSiteAdmin /
  IsSystemAdmin / IsSubDivision. A user with no group has no flags.
* Sites: Super Admin → all sites by name (site dropdown, 01d S1); everyone else, System
  Admin included (F22 kept) → their `UserSites`. Legacy's `UserSites` claim holds the
  UserSites **row** ids (finding for 101); the API returns real site ids.
* Towers: sub-division users that are neither Super nor System Admin → towers whose
  `UserId` is the user (F19: computed per request, never trusted from the client).
* Default current site at login (cookie cleared): Super Admin → first site by name;
  otherwise the user's first `UserSites` row (lowest Id [Inferred: `FirstOrDefault`]);
  none → None (decision (c): login refused).

Read-only: ApplicationUsersInGroups, ApplicationRoleGroups, ApplicationRolesInGroups,
ApplicationRoles, UserSites, Sites, Towers.
"""

from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.legacy import (
    ApplicationRole,
    ApplicationRoleGroup,
    ApplicationRoleInGroup,
    ApplicationUser,
    ApplicationUserInGroup,
    Site,
    Tower,
    UserSite,
)
from app.schemas.auth import Flags, SiteRef


@dataclass
class UserContext:
    user: ApplicationUser
    permissions: list[str] = field(default_factory=list)
    flags: Flags = field(default_factory=Flags)
    sites: list[SiteRef] = field(default_factory=list)
    tower_ids: list[int] = field(default_factory=list)
    default_site_id: int | None = None


async def find_user_by_name(session: AsyncSession, user_name: str | None) -> ApplicationUser | None:
    """Identity 2 `FindByName`: `UserName.ToUpper() == userName.ToUpper()`, first row."""
    if not user_name:
        return None
    stmt = (
        select(ApplicationUser)
        .where(func.upper(ApplicationUser.user_name) == user_name.upper())
        .order_by(ApplicationUser.id)
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def find_user_by_email(session: AsyncSession, email: str | None) -> ApplicationUser | None:
    """Identity 2 `FindByEmail` (emails are not unique here, CPSM-44): first row by Id."""
    if not email:
        return None
    stmt = (
        select(ApplicationUser)
        .where(func.upper(ApplicationUser.email) == email.upper())
        .order_by(ApplicationUser.id)
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def first_user_site_id(session: AsyncSession, user_id: int) -> int | None:
    stmt = (
        select(UserSite.site_id)
        .where(UserSite.application_user_id == user_id)
        .order_by(UserSite.id)
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def build_user_context(session: AsyncSession, user: ApplicationUser) -> UserContext:
    ctx = UserContext(user=user)

    group_ids = list(
        (
            await session.execute(
                select(ApplicationUserInGroup.application_role_group_id)
                .where(ApplicationUserInGroup.application_user_id == user.id)
                .order_by(ApplicationUserInGroup.id)
            )
        ).scalars()
    )
    if group_ids:
        role_ids = set(
            (
                await session.execute(
                    select(ApplicationRoleInGroup.application_role_id).where(
                        ApplicationRoleInGroup.application_role_group_id.in_(group_ids)
                    )
                )
            ).scalars()
        )
        if role_ids:
            ctx.permissions = [
                name
                for name in (
                    await session.execute(
                        select(ApplicationRole.name)
                        .where(ApplicationRole.id.in_(role_ids))
                        .order_by(ApplicationRole.id)
                    )
                ).scalars()
                if name is not None
            ]
        groups = list(
            (
                await session.execute(
                    select(ApplicationRoleGroup).where(ApplicationRoleGroup.id.in_(group_ids))
                )
            ).scalars()
        )
        ctx.flags = Flags(
            is_super_admin=any(g.is_super_admin for g in groups),
            is_end_user=any(g.is_end_user for g in groups),
            is_site_admin=any(g.is_site_admin for g in groups),
            is_system_admin=any(g.is_system_admin for g in groups),
            is_sub_division=any(g.is_sub_division for g in groups),
        )

    if ctx.flags.is_super_admin:
        rows = (await session.execute(select(Site.id, Site.name).order_by(Site.name))).all()
        ctx.sites = [SiteRef(id=r.id, name=r.name) for r in rows]
        ctx.default_site_id = ctx.sites[0].id if ctx.sites else None
    else:
        rows = (
            await session.execute(
                select(Site.id, Site.name)
                .join(UserSite, UserSite.site_id == Site.id)
                .where(UserSite.application_user_id == user.id)
                .order_by(UserSite.id)
            )
        ).all()
        seen: set[int] = set()
        for r in rows:
            if r.id not in seen:
                seen.add(r.id)
                ctx.sites.append(SiteRef(id=r.id, name=r.name))
        ctx.default_site_id = await first_user_site_id(session, user.id)

    if ctx.flags.is_sub_division and not (ctx.flags.is_super_admin or ctx.flags.is_system_admin):
        ctx.tower_ids = list(
            (
                await session.execute(
                    select(Tower.id).where(Tower.user_id == user.id).order_by(Tower.id)
                )
            ).scalars()
        )
    return ctx
