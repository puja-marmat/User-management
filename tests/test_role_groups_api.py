"""
R3-R4 (Create New Role Group form) on the synthetic SQLite copy of the legacy tables:
SuperAdmin area, own-permission tick-list, legacy flags per UserType, F25 negatives.
"""

from dataclasses import dataclass

from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import func, select

from app.core.database import get_reader_db, get_writer_db
from app.models.legacy import ApplicationRole, ApplicationRoleGroup, ApplicationRoleInGroup
from tests.auth_support import GOOD_PASSWORD, Seed, make_engine, seed, session_dependency


@dataclass
class Env:
    client: AsyncClient
    factory: object
    seed: Seed
    role_ids: dict[str, int]


async def _give_super(factory, names: list[str]) -> dict[str, int]:
    """Adds roles to the seeded "Super" group; returns name → role id for all roles."""
    async with factory() as s:
        g = (
            await s.execute(
                select(ApplicationRoleGroup).where(ApplicationRoleGroup.name == "Super")
            )
        ).scalar_one()
        for n in names:
            role = ApplicationRole(name=n)
            s.add(role)
            await s.flush()
            s.add(
                ApplicationRoleInGroup(application_role_group_id=g.id, application_role_id=role.id)
            )
        await s.commit()
        return {r.name: r.id for r in (await s.execute(select(ApplicationRole))).scalars()}


@pytest.fixture
async def env(tmp_path):
    from app.main import create_app

    engine = await make_engine(tmp_path)
    dep, factory = session_dependency(engine)
    data = await seed(factory)
    role_ids = await _give_super(factory, ["Add Site", "Add Role Group", "Recharge"])
    app = create_app()
    app.dependency_overrides[get_writer_db] = dep
    app.dependency_overrides[get_reader_db] = dep
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield Env(client, factory, data, role_ids)
    await engine.dispose()


async def _token(env: Env, user_name: str = "synthetic.super") -> dict[str, str]:
    r = await env.client.post(
        "/auth/login", json={"userName": user_name, "password": GOOD_PASSWORD}
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['accessToken']}"}


async def _groups(env: Env, name: str):
    async with env.factory() as s:
        return list(
            (
                await s.execute(
                    select(ApplicationRoleGroup).where(ApplicationRoleGroup.name == name)
                )
            ).scalars()
        )


async def _count(env: Env, model) -> int:
    async with env.factory() as s:
        return (await s.execute(select(func.count()).select_from(model))).scalar_one()


async def test_permission_options_are_the_callers_own_in_role_order(env):
    r = await env.client.get("/role-groups/permission-options", headers=await _token(env))
    assert r.status_code == 200, r.text
    assert [p["name"] for p in r.json()] == ["Add Site", "Add Role Group", "Recharge"]
    assert r.json()[0]["id"] == env.role_ids["Add Site"]


async def test_non_super_admin_is_forbidden(env):
    headers = await _token(env, "synthetic.admin")
    assert (
        await env.client.get("/role-groups/permission-options", headers=headers)
    ).status_code == 403
    r = await env.client.post("/role-groups", json={"name": "X"}, headers=headers)
    assert r.status_code == 403
    assert await _groups(env, "X") == []


async def test_no_token_is_401(env):
    assert (await env.client.get("/role-groups/permission-options")).status_code == 401


async def test_create_sets_flags_site_and_roles(env):
    rows_before = await _count(env, ApplicationRoleInGroup)
    picked = [env.role_ids["Add Site"], env.role_ids["Recharge"], env.role_ids["Add Site"]]
    r = await env.client.post(
        "/role-groups",
        json={"name": "Meter Readers", "userType": "SubDivision", "roleIds": picked},
        headers=await _token(env),
    )
    assert r.status_code == 201, r.text
    [g] = await _groups(env, "Meter Readers")
    assert r.json()["id"] == g.id
    assert g.site_id == env.seed.site_a  # super admin default = first site by name
    assert (g.is_sub_division, g.is_site_admin, g.is_end_user) == (True, False, False)
    assert (g.is_super_admin, g.is_system_admin, g.is_editable) == (False, False, True)
    assert g.created_by_user_id == env.seed.super_id
    async with env.factory() as s:
        linked = set(
            (
                await s.execute(
                    select(ApplicationRoleInGroup.application_role_id).where(
                        ApplicationRoleInGroup.application_role_group_id == g.id
                    )
                )
            ).scalars()
        )
    assert linked == {env.role_ids["Add Site"], env.role_ids["Recharge"]}
    assert await _count(env, ApplicationRoleInGroup) == rows_before + 2


async def test_default_user_type_sets_no_flag(env):
    r = await env.client.post("/role-groups", json={"name": "Staff"}, headers=await _token(env))
    assert r.status_code == 201, r.text
    [g] = await _groups(env, "Staff")
    assert not (g.is_site_admin or g.is_end_user or g.is_sub_division)


async def test_role_the_caller_does_not_hold_is_refused(env):
    r = await env.client.post(
        "/role-groups",
        json={"name": "Sneaky", "roleIds": [env.role_ids["Save User"]]},
        headers=await _token(env),
    )
    assert r.status_code == 403
    assert r.json()["errorCode"] == "PERMISSION_NOT_ALLOWED"
    assert await _groups(env, "Sneaky") == []


async def test_super_admin_flag_cannot_be_posted(env):
    r = await env.client.post(
        "/role-groups",
        json={"name": "Escalate", "isSuperAdmin": True, "userType": "SuperAdmin"},
        headers=await _token(env),
    )
    assert r.status_code == 422
    assert await _groups(env, "Escalate") == []


async def test_name_rules(env):
    headers = await _token(env)
    r = await env.client.post("/role-groups", json={"name": "  "}, headers=headers)
    assert r.status_code == 422
    assert r.json()["errors"] == [{"field": "name", "message": "The Name field is required."}]
    r = await env.client.post("/role-groups", json={"name": "x" * 51}, headers=headers)
    assert r.status_code == 422
    # same name, other case, same site → taken ("Super" is seeded in site A)
    r = await env.client.post("/role-groups", json={"name": "SUPER"}, headers=headers)
    assert r.status_code == 422
    assert r.json()["errors"][0]["field"] == "name"


async def test_without_add_role_group_permission_is_forbidden(env):
    async with env.factory() as s:
        role_id = env.role_ids["Add Role Group"]
        link = (
            await s.execute(
                select(ApplicationRoleInGroup).where(
                    ApplicationRoleInGroup.application_role_id == role_id
                )
            )
        ).scalar_one()
        await s.delete(link)
        await s.commit()
    r = await env.client.post("/role-groups", json={"name": "Nope"}, headers=await _token(env))
    assert r.status_code == 403
