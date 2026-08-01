"""Core-only health, diagnostics, settings, and manual checks."""

from app.admin_api.server import create_admin_api
from app.admin_api.service import CoreAdminService

__all__ = [
    "CoreAdminService",
    "create_admin_api",
]
