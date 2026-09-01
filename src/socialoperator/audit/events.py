from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from socialoperator.knowledge.database import Database


@dataclass(frozen=True, slots=True)
class AuditLogger:
    database: Database
    session_id: str | None = None

    def write(self, event_type: str, payload: Mapping[str, Any]) -> str:
        return self.database.append_audit_event(
            event_type,
            payload,
            session_id=self.session_id,
        )
