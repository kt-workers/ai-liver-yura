"""Standalone Streaming Subsystem Admin API."""

from subsystems.streaming.admin_api.server import create_streaming_admin_api
from subsystems.streaming.admin_api.service import StreamingAdminService

__all__ = ["StreamingAdminService", "create_streaming_admin_api"]
