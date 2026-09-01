from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from socialoperator.knowledge.database import Database, canonical_json, utc_now
from socialoperator.knowledge.service import proposal_sha256
from socialoperator.types import PublicationStatus, ReviewStatus, Sensitivity

PUBLIC_TABLES = {"publication", "portfolio_items", "portfolio_assets"}
PUBLIC_ASSET_MEDIA_TYPES = {"image/png", "image/jpeg", "image/webp", "text/plain"}
PUBLIC_ASSET_RIGHTS = {"created_by_user", "owned_by_user", "user_created", "user_owned"}
FORBIDDEN_PUBLIC_PATTERNS = (
    re.compile(r"private[-_ ]?only", re.IGNORECASE),
    re.compile(r"do[-_ ]?not[-_ ]?publish", re.IGNORECASE),
    re.compile(
        r"\b(?:password|passkey|otp|one[-_ ]?time[-_ ]?code|recovery[-_ ]?code)\b", re.IGNORECASE
    ),
    re.compile(r"\b(?:secret|api[-_ ]?key|access[-_ ]?token|refresh[-_ ]?token)\b", re.IGNORECASE),
    re.compile(r"/home/[A-Za-z0-9._-]+"),
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    re.compile(r"\b(?:\d[ -]*?){13,16}\b"),
)


@dataclass(frozen=True, slots=True)
class PublicationBuild:
    publication_version_id: str
    version_number: int
    version_database_path: Path
    active_database_path: Path
    manifest_path: Path
    manifest_sha256: str
    item_count: int
    asset_count: int


class PublicationError(RuntimeError):
    """Raised when the public snapshot cannot be built safely."""


class PublicationBuilder:
    def __init__(
        self,
        private_database: Database,
        output_dir: str | Path,
        *,
        artifact_root: str | Path | None = None,
    ) -> None:
        self.private_database = private_database
        self.output_dir = Path(output_dir).expanduser().resolve()
        self.artifact_root = (
            Path(artifact_root).expanduser().resolve()
            if artifact_root is not None
            else private_database.path.parent / "artifacts"
        )

    def build(self) -> PublicationBuild:
        if self.private_database.path == self.output_dir / "portfolio-public.sqlite":
            raise PublicationError(
                "public snapshot must be physically separate from the private database"
            )
        self.output_dir.mkdir(parents=True, exist_ok=True)
        with self.private_database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM portfolio_items
                WHERE review_status = ?
                  AND publication_status IN (?, ?)
                  AND sensitivity = ?
                ORDER BY slug, portfolio_item_id
                """,
                (
                    ReviewStatus.APPROVED.value,
                    PublicationStatus.CANDIDATE.value,
                    PublicationStatus.PUBLISHED.value,
                    Sensitivity.PUBLIC.value,
                ),
            ).fetchall()
            version_number = int(
                connection.execute(
                    "SELECT COALESCE(MAX(version_number), 0) + 1 FROM publication_versions"
                ).fetchone()[0]
            )
            approved: list[tuple[sqlite3.Row, str, str]] = []
            approved_assets: list[tuple[sqlite3.Row, sqlite3.Row, Path, str]] = []
            for row in rows:
                item_hash = proposal_sha256(row)
                _assert_public_text_clean(str(row["title"]), "title")
                _assert_public_text_clean(str(row["summary"]), "summary")
                _assert_public_text_clean(str(row["body"]), "body")
                review = connection.execute(
                    """
                    SELECT review_decision_id, proposal_sha256
                    FROM review_decisions
                    WHERE portfolio_item_id = ? AND decision = ?
                    ORDER BY decided_at DESC, rowid DESC LIMIT 1
                    """,
                    (row["portfolio_item_id"], ReviewStatus.APPROVED.value),
                ).fetchone()
                if review is None or review["proposal_sha256"] != item_hash:
                    raise PublicationError(
                        f"item lacks current exact-hash approval: {row['portfolio_item_id']}"
                    )
                approved.append((row, item_hash, str(review["review_decision_id"])))
                approved_assets.extend(self._approved_assets_for_item(connection, row=row))
        publication_id = str(uuid4())
        created_at = utc_now()
        manifest_items = [
            {
                "portfolio_item_id": str(row["portfolio_item_id"]),
                "slug": str(row["slug"]),
                "item_sha256": item_hash,
                "review_decision_id": review_id,
            }
            for row, item_hash, review_id in approved
        ]
        review_digest = hashlib.sha256(
            canonical_json(
                {"reviews": [item["review_decision_id"] for item in manifest_items]}
            ).encode()
        ).hexdigest()
        manifest_assets = [
            {
                "portfolio_item_id": str(row["portfolio_item_id"]),
                "slug": str(row["slug"]),
                "capture_artifact_id": str(asset["capture_artifact_id"]),
                "public_relative_path": public_relative_path,
                "asset_sha256": str(asset["sha256"]),
                "media_type": str(asset["media_type"]),
                "byte_length": int(asset["byte_length"]),
            }
            for row, asset, _, public_relative_path in approved_assets
        ]
        manifest_without_hash = {
            "publication_version_id": publication_id,
            "version_number": version_number,
            "created_at": created_at,
            "item_count": len(manifest_items),
            "asset_count": len(manifest_assets),
            "items": manifest_items,
            "assets": manifest_assets,
        }
        manifest_sha = hashlib.sha256(canonical_json(manifest_without_hash).encode()).hexdigest()
        manifest = {**manifest_without_hash, "manifest_sha256": manifest_sha}
        version_database = self.output_dir / f"portfolio-public-v{version_number:04d}.sqlite"
        version_manifest = self.output_dir / f"portfolio-public-v{version_number:04d}.json"
        active_database = self.output_dir / "portfolio-public.sqlite"
        temporary_database = version_database.with_suffix(".sqlite.tmp")
        temporary_manifest = version_manifest.with_suffix(".json.tmp")
        temporary_database.unlink(missing_ok=True)
        with sqlite3.connect(temporary_database) as public:
            public.executescript(
                """
                PRAGMA foreign_keys = ON;
                CREATE TABLE publication (
                    publication_version_id TEXT PRIMARY KEY,
                    version_number INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    manifest_sha256 TEXT NOT NULL,
                    item_count INTEGER NOT NULL,
                    asset_count INTEGER NOT NULL
                ) STRICT;
                CREATE TABLE portfolio_items (
                    slug TEXT PRIMARY KEY,
                    item_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    body TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    item_sha256 TEXT NOT NULL
                ) WITHOUT ROWID, STRICT;
                CREATE TABLE portfolio_assets (
                    item_slug TEXT NOT NULL REFERENCES portfolio_items(slug),
                    public_relative_path TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    asset_sha256 TEXT NOT NULL,
                    byte_length INTEGER NOT NULL CHECK (byte_length >= 0),
                    source_label TEXT NOT NULL,
                    PRIMARY KEY (item_slug, public_relative_path)
                ) WITHOUT ROWID, STRICT;
                """
            )
            public.execute(
                "INSERT INTO publication VALUES (?, ?, ?, ?, ?, ?)",
                (
                    publication_id,
                    version_number,
                    created_at,
                    manifest_sha,
                    len(approved),
                    len(approved_assets),
                ),
            )
            public.executemany(
                """
                INSERT INTO portfolio_items(
                    slug, item_type, title, summary, body, updated_at, item_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row["slug"],
                        row["item_type"],
                        row["title"],
                        row["summary"],
                        row["body"],
                        row["updated_at"],
                        item_hash,
                    )
                    for row, item_hash, _ in approved
                ],
            )
            public.executemany(
                """
                INSERT INTO portfolio_assets(
                    item_slug, public_relative_path, media_type, asset_sha256,
                    byte_length, source_label
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row["slug"],
                        public_relative_path,
                        asset["media_type"],
                        asset["sha256"],
                        asset["byte_length"],
                        str(json.loads(str(asset["metadata_json"])).get("source_label", "asset")),
                    )
                    for row, asset, _, public_relative_path in approved_assets
                ],
            )
            public.commit()
        temporary_database.chmod(0o644)
        for _, asset, source_path, public_relative_path in approved_assets:
            target = self.output_dir / public_relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary_asset = target.with_suffix(target.suffix + ".tmp")
            shutil.copy2(source_path, temporary_asset)
            actual_hash = hashlib.sha256(temporary_asset.read_bytes()).hexdigest()
            if actual_hash != asset["sha256"]:
                temporary_asset.unlink(missing_ok=True)
                raise PublicationError(f"asset hash mismatch while publishing {asset['sha256']}")
            temporary_asset.chmod(0o644)
            os.replace(temporary_asset, target)
        temporary_manifest.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary_manifest.chmod(0o644)
        verify_public_snapshot(
            temporary_database,
            expected_manifest_sha256=manifest_sha,
            asset_root=self.output_dir,
        )
        os.replace(temporary_database, version_database)
        os.replace(temporary_manifest, version_manifest)
        active_temporary = active_database.with_suffix(".sqlite.tmp")
        shutil.copy2(version_database, active_temporary)
        os.replace(active_temporary, active_database)
        with self.private_database.connect() as connection:
            connection.execute(
                """
                INSERT INTO publication_versions(
                    publication_version_id, version_number, manifest_sha256, created_at,
                    status, approved_review_sha256, retention_protected
                ) VALUES (?, ?, ?, ?, 'published', ?, 1)
                """,
                (publication_id, version_number, manifest_sha, created_at, review_digest),
            )
            connection.executemany(
                """
                INSERT INTO publication_items(
                    publication_version_id, portfolio_item_id, item_sha256
                ) VALUES (?, ?, ?)
                """,
                [
                    (publication_id, row["portfolio_item_id"], item_hash)
                    for row, item_hash, _ in approved
                ],
            )
            connection.executemany(
                """
                INSERT INTO publication_assets(
                    publication_version_id, capture_artifact_id, public_relative_path, asset_sha256
                ) VALUES (?, ?, ?, ?)
                """,
                [
                    (
                        publication_id,
                        asset["capture_artifact_id"],
                        public_relative_path,
                        asset["sha256"],
                    )
                    for _, asset, _, public_relative_path in approved_assets
                ],
            )
            connection.executemany(
                """
                UPDATE portfolio_items SET publication_status = ?, updated_at = ?
                WHERE portfolio_item_id = ?
                """,
                [
                    (PublicationStatus.PUBLISHED.value, created_at, row["portfolio_item_id"])
                    for row, _, _ in approved
                ],
            )
        self.private_database.append_audit_event(
            "PUBLICATION_BUILT",
            {
                "publication_version_id": publication_id,
                "version_number": version_number,
                "manifest_sha256": manifest_sha,
                "item_count": len(approved),
                "asset_count": len(approved_assets),
                "active_database": str(active_database),
            },
        )
        return PublicationBuild(
            publication_version_id=publication_id,
            version_number=version_number,
            version_database_path=version_database,
            active_database_path=active_database,
            manifest_path=version_manifest,
            manifest_sha256=manifest_sha,
            item_count=len(approved),
            asset_count=len(approved_assets),
        )

    def _approved_assets_for_item(
        self,
        connection: sqlite3.Connection,
        *,
        row: sqlite3.Row,
    ) -> list[tuple[sqlite3.Row, sqlite3.Row, Path, str]]:
        assets = connection.execute(
            """
            SELECT DISTINCT ca.*
            FROM portfolio_item_claims pic
            JOIN claim_evidence ce ON ce.claim_id = pic.claim_id
            JOIN observations o ON o.observation_id = ce.observation_id
            JOIN capture_artifacts ca ON ca.capture_artifact_id = o.capture_artifact_id
            WHERE pic.portfolio_item_id = ?
              AND ca.sensitivity = ?
              AND ca.redacted = 1
            ORDER BY ca.sha256, ca.capture_artifact_id
            """,
            (row["portfolio_item_id"], Sensitivity.PUBLIC.value),
        ).fetchall()
        approved_assets: list[tuple[sqlite3.Row, sqlite3.Row, Path, str]] = []
        for asset in assets:
            metadata = json.loads(str(asset["metadata_json"]))
            publication = metadata.get("publication", {})
            if not isinstance(publication, dict) or publication.get("allowed") is not True:
                continue
            rights = str(publication.get("rights", ""))
            if rights not in PUBLIC_ASSET_RIGHTS:
                raise PublicationError(
                    f"asset lacks approved publication rights: {asset['sha256']}"
                )
            media_type = str(asset["media_type"])
            if media_type not in PUBLIC_ASSET_MEDIA_TYPES:
                raise PublicationError(f"asset media type is not allowed: {media_type}")
            relative_path = Path(str(asset["relative_path"]))
            if relative_path.is_absolute() or ".." in relative_path.parts:
                raise PublicationError(f"unsafe private asset path: {relative_path}")
            source_path = self.artifact_root / relative_path
            if not source_path.is_file():
                raise PublicationError(f"approved asset is missing: {asset['sha256']}")
            data = source_path.read_bytes()
            if hashlib.sha256(data).hexdigest() != asset["sha256"]:
                raise PublicationError(f"approved asset hash mismatch: {asset['sha256']}")
            if len(data) != asset["byte_length"]:
                raise PublicationError(f"approved asset size mismatch: {asset['sha256']}")
            _assert_public_bytes_clean(data, label=f"asset {asset['sha256']}")
            public_relative_path = Path("assets") / "sha256" / str(asset["sha256"])
            approved_assets.append((row, asset, source_path, public_relative_path.as_posix()))
        return approved_assets

    def rollback(self, version_number: int) -> Path:
        version_database = self.output_dir / f"portfolio-public-v{version_number:04d}.sqlite"
        if not version_database.is_file():
            raise PublicationError(f"unknown publication version: {version_number}")
        verification = verify_public_snapshot(version_database, asset_root=self.output_dir)
        active_database = self.output_dir / "portfolio-public.sqlite"
        active_temporary = active_database.with_suffix(".sqlite.tmp")
        shutil.copy2(version_database, active_temporary)
        os.replace(active_temporary, active_database)
        with self.private_database.connect() as connection:
            row = connection.execute(
                "SELECT publication_version_id FROM publication_versions WHERE version_number = ?",
                (version_number,),
            ).fetchone()
            if row is None:
                raise PublicationError(
                    f"private publication ledger has no version {version_number}"
                )
            connection.execute(
                "UPDATE publication_versions SET status = 'superseded' WHERE status = 'published'"
            )
            connection.execute(
                "UPDATE publication_versions SET status = 'published' WHERE version_number = ?",
                (version_number,),
            )
        self.private_database.append_audit_event(
            "PUBLICATION_ROLLED_BACK",
            {
                "version_number": version_number,
                "manifest_sha256": verification["manifest_sha256"],
                "active_database": str(active_database),
            },
        )
        return active_database


def verify_public_snapshot(
    path: str | Path,
    *,
    expected_manifest_sha256: str | None = None,
    asset_root: str | Path | None = None,
) -> dict[str, object]:
    snapshot = Path(path).expanduser().resolve()
    root = Path(asset_root).expanduser().resolve() if asset_root is not None else snapshot.parent
    with sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        tables = {
            str(row["name"])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        publication = connection.execute("SELECT * FROM publication").fetchone()
        item_count = int(connection.execute("SELECT COUNT(*) FROM portfolio_items").fetchone()[0])
        asset_rows = connection.execute("SELECT * FROM portfolio_assets").fetchall()
        for row in connection.execute("SELECT title, summary, body FROM portfolio_items"):
            _assert_public_text_clean(str(row["title"]), "public title")
            _assert_public_text_clean(str(row["summary"]), "public summary")
            _assert_public_text_clean(str(row["body"]), "public body")
    if integrity != "ok":
        raise PublicationError(f"public snapshot integrity failed: {integrity}")
    if tables != PUBLIC_TABLES:
        raise PublicationError(f"unexpected public tables: {sorted(tables - PUBLIC_TABLES)}")
    if publication is None:
        raise PublicationError("public snapshot has no publication record")
    if expected_manifest_sha256 and publication["manifest_sha256"] != expected_manifest_sha256:
        raise PublicationError("public snapshot manifest hash mismatch")
    if int(publication["item_count"]) != item_count:
        raise PublicationError("public snapshot item count mismatch")
    if int(publication["asset_count"]) != len(asset_rows):
        raise PublicationError("public snapshot asset count mismatch")
    for asset in asset_rows:
        relative_path = Path(str(asset["public_relative_path"]))
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise PublicationError(f"unsafe public asset path: {relative_path}")
        asset_path = root / relative_path
        if not asset_path.is_file():
            raise PublicationError(f"public asset is missing: {relative_path}")
        data = asset_path.read_bytes()
        if hashlib.sha256(data).hexdigest() != asset["asset_sha256"]:
            raise PublicationError(f"public asset hash mismatch: {relative_path}")
        if len(data) != asset["byte_length"]:
            raise PublicationError(f"public asset size mismatch: {relative_path}")
        _assert_public_bytes_clean(data, label=str(relative_path))
    return {
        "path": str(snapshot),
        "integrity": integrity,
        "tables": sorted(tables),
        "manifest_sha256": str(publication["manifest_sha256"]),
        "item_count": item_count,
        "asset_count": len(asset_rows),
        "ok": True,
    }


def _assert_public_text_clean(value: str, label: str) -> None:
    for pattern in FORBIDDEN_PUBLIC_PATTERNS:
        if pattern.search(value):
            raise PublicationError(f"forbidden public content in {label}: {pattern.pattern}")


def _assert_public_bytes_clean(data: bytes, *, label: str) -> None:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return
    _assert_public_text_clean(text, label)
