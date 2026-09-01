from __future__ import annotations

import hashlib
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from socialoperator.knowledge.database import Database, canonical_json, utc_now
from socialoperator.types import Sensitivity


@dataclass(frozen=True, slots=True)
class StoredArtifact:
    artifact_id: str
    sha256: str
    path: Path
    relative_path: str
    media_type: str
    byte_length: int


class ArtifactStore:
    def __init__(self, root: str | Path, database: Database, *, file_mode: int = 0o600) -> None:
        self.root = Path(root).expanduser().resolve()
        self.database = database
        self.file_mode = file_mode
        self.root.mkdir(parents=True, exist_ok=True)
        self.root.chmod(0o700)

    def put_bytes(
        self,
        data: bytes,
        *,
        media_type: str,
        sensitivity: Sensitivity = Sensitivity.PRIVATE,
        source_page_id: str | None = None,
        parent_artifact_id: str | None = None,
        redacted: bool = False,
        metadata: Mapping[str, Any] | None = None,
    ) -> StoredArtifact:
        digest = hashlib.sha256(data).hexdigest()
        relative = Path("sha256") / digest[:2] / digest[2:4] / digest
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.parent.chmod(0o700)
        if target.exists():
            existing_digest = hashlib.sha256(target.read_bytes()).hexdigest()
            if existing_digest != digest:
                raise ValueError(f"artifact hash collision at {target}")
        else:
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(data)
                handle.flush()
            temporary.chmod(self.file_mode)
            temporary.replace(target)
        artifact_id = str(uuid4())
        with self.database.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM capture_artifacts WHERE sha256 = ?", (digest,)
            ).fetchone()
            if existing:
                return StoredArtifact(
                    artifact_id=str(existing["capture_artifact_id"]),
                    sha256=digest,
                    path=target,
                    relative_path=str(existing["relative_path"]),
                    media_type=str(existing["media_type"]),
                    byte_length=int(existing["byte_length"]),
                )
            connection.execute(
                """
                INSERT INTO capture_artifacts(
                    capture_artifact_id, source_page_id, parent_artifact_id, sha256,
                    relative_path, media_type, byte_length, captured_at, sensitivity,
                    redacted, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_id,
                    source_page_id,
                    parent_artifact_id,
                    digest,
                    str(relative),
                    media_type,
                    len(data),
                    utc_now(),
                    sensitivity.value,
                    int(redacted),
                    canonical_json(metadata),
                ),
            )
        return StoredArtifact(
            artifact_id=artifact_id,
            sha256=digest,
            path=target,
            relative_path=str(relative),
            media_type=media_type,
            byte_length=len(data),
        )

    def verify(self) -> dict[str, object]:
        checked = 0
        errors: list[str] = []
        with self.database.connect() as connection:
            rows = connection.execute("SELECT * FROM capture_artifacts ORDER BY sha256").fetchall()
        for row in rows:
            path = self.root / str(row["relative_path"])
            if not path.is_file():
                errors.append(f"missing:{row['sha256']}")
                continue
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != row["sha256"]:
                errors.append(f"hash:{row['sha256']}")
            if path.stat().st_size != row["byte_length"]:
                errors.append(f"size:{row['sha256']}")
            checked += 1
        return {"checked": checked, "errors": errors, "ok": not errors}
