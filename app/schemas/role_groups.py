"""Role groups (01d §2.4, R3-R4): the Create New Role Group form."""

from enum import StrEnum
import uuid

from pydantic import Field

from app.schemas.common import CamelModel


class UserType(StrEnum):
    """The form's UserType drop-down; each sets one legacy flag, Default sets none (staff)."""

    DEFAULT = "Default"
    SITE_ADMIN = "SiteAdmin"
    END_USER = "EndUser"
    SUB_DIVISION = "SubDivision"


class PermissionOption(CamelModel):
    id: int
    name: str


class CreateRoleGroupRequest(CamelModel):
    name: str | None = None
    user_type: UserType = UserType.DEFAULT
    role_ids: list[int] = Field(default_factory=list)


class RoleGroupCreated(CamelModel):
    id: int
    guid: uuid.UUID
