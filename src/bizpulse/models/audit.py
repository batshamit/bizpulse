"""Admin audit-log entry."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field

from bizpulse.models.common import StrictModel, utcnow


class AuditEvent(StrictModel):
    """One operator action recorded in admin_audit_log."""

    id: UUID = Field(default_factory=uuid4)
    occurred_at: datetime = Field(default_factory=utcnow)
    actor: str = Field(min_length=1, description="Operator identity. Today: 'admin' (single key); future: user id.")
    action: str = Field(
        min_length=1,
        description="Verb-noun action, e.g., 'tenant.update', 'tenant.impersonate', 'tenant.cleanup', 'admin.login'.",
    )
    target_kind: str | None = Field(default=None, description="What kind of object was affected: 'tenant', 'run', or None for system events.")
    target_id: str | None = Field(default=None, description="UUID or pattern identifying the target.")
    details: dict[str, Any] = Field(default_factory=dict, description="Diff / extra context, e.g., {'before': {...}, 'after': {...}}.")
    request_ip: str | None = None
