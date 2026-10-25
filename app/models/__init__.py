"""
Model registry. Alembic autogenerate compares `target_metadata` (iam only) with the
database. Import every iam model module here as it is added (M1).
"""

from app.models.base import IAM_SCHEMA, IamBase, LegacyBase


# M1: from app.models.iam import users, credentials, organisation, ...

target_metadata = IamBase.metadata

__all__ = ["IAM_SCHEMA", "IamBase", "LegacyBase", "target_metadata"]
