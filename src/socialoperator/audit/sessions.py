from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from socialoperator.audit.events import AuditLogger
from socialoperator.knowledge.database import Database
from socialoperator.types import OperatorState


@dataclass(slots=True)
class SessionManager:
    database: Database
    session_id: str | None = None

    def start(self, metadata: Mapping[str, Any] | None = None) -> str:
        if self.session_id is not None:
            raise RuntimeError("session is already active")
        self.session_id = self.database.create_session(metadata)
        AuditLogger(self.database, self.session_id).write("SESSION_CREATED", metadata or {})
        return self.session_id

    def transition(
        self,
        state: OperatorState,
        *,
        ended: bool = False,
        last_verified_action_id: str | None = None,
    ) -> None:
        if self.session_id is None:
            raise RuntimeError("no active session")
        self.database.transition_session(
            self.session_id,
            state,
            ended=ended,
            last_verified_action_id=last_verified_action_id,
        )
        AuditLogger(self.database, self.session_id).write(
            "SESSION_TRANSITION",
            {
                "state": state.value,
                "ended": ended,
                "last_verified_action_id": last_verified_action_id,
            },
        )


def recover_sessions(database: Database) -> list[str]:
    session_ids = database.recover_stale_sessions()
    logger = AuditLogger(database)
    for session_id in session_ids:
        logger.write(
            "SESSION_RECOVERED_PAUSED",
            {"session_id": session_id, "action_replayed": False},
        )
    return session_ids
