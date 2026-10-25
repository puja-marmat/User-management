"""Top-level router. No version prefix (plan §7, DEC-26)."""

from fastapi import APIRouter

from app.routers import auth, health


router = APIRouter()

router.include_router(health.router)
router.include_router(auth.router)  # P1-M2: A1-A10
# P1-M3+: site context, users, role groups, API access (01d §2)
