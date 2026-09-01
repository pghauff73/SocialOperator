from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from socialoperator.knowledge.publication import verify_public_snapshot
from socialoperator.portfolio.accessibility import check_static_export
from socialoperator.portfolio.app import (
    PORTFOLIO_SECTIONS,
    SnapshotRepository,
    _collection_structured_data,
    _item_structured_data,
    _section_structured_data,
    build_section_payloads,
    portfolio_template_dir,
    section_for_item_type,
)


@dataclass(frozen=True, slots=True)
class StaticExport:
    output_dir: Path
    manifest_path: Path
    manifest_sha256: str
    file_count: int


def export_static_site(snapshot_path: str | Path, output_dir: str | Path) -> StaticExport:
    snapshot = Path(snapshot_path).expanduser().resolve()
    output = Path(output_dir).expanduser().resolve()
    verify_public_snapshot(snapshot)
    repository = SnapshotRepository(snapshot)
    environment = Environment(
        loader=FileSystemLoader(str(portfolio_template_dir())),
        autoescape=select_autoescape(("html", "xml")),
    )
    output.mkdir(parents=True, exist_ok=True)
    publication = repository.publication()
    items = repository.list_items()
    index_html = environment.get_template("index.html").render(
        publication=publication,
        items=items,
        sections=build_section_payloads(items),
        section_nav=PORTFOLIO_SECTIONS,
        page_title="Profile Portfolio",
        description="Verified public portfolio generated from approved data.",
        structured_data=json.dumps(_collection_structured_data(items), sort_keys=True),
    )
    _write_public_file(output / "index.html", index_html.encode())
    for section in PORTFOLIO_SECTIONS:
        section_items = repository.list_section_items(section)
        section_html = environment.get_template("section.html").render(
            publication=publication,
            section=section,
            items=section_items,
            section_nav=PORTFOLIO_SECTIONS,
            page_title=section.label,
            description=section.description,
            structured_data=json.dumps(
                _section_structured_data(section, section_items),
                sort_keys=True,
            ),
        )
        _write_public_file(output / section.slug / "index.html", section_html.encode())
    for item in items:
        slug = str(item["slug"])
        item_html = environment.get_template("item.html").render(
            publication=publication,
            item=item,
            assets=repository.get_item_assets(slug),
            section_nav=PORTFOLIO_SECTIONS,
            section=section_for_item_type(str(item["item_type"])),
            page_title=item["title"],
            description=item["summary"],
            structured_data=json.dumps(_item_structured_data(item), sort_keys=True),
        )
        _write_public_file(output / "items" / slug / "index.html", item_html.encode())
    for item in items:
        for asset in repository.get_item_assets(str(item["slug"])):
            relative_path = Path(str(asset["public_relative_path"]))
            source = snapshot.parent / relative_path
            target = output / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(target.suffix + ".tmp")
            shutil.copy2(source, temporary)
            os.replace(temporary, target)
            target.chmod(0o644)
    errors = check_static_export(output)
    if errors:
        raise ValueError("static export accessibility check failed: " + "; ".join(errors))
    manifest_entries = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "static-export-manifest.json":
            data = path.read_bytes()
            manifest_entries.append(
                {
                    "path": path.relative_to(output).as_posix(),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "size": len(data),
                }
            )
    manifest_payload = {
        "snapshot": snapshot.name,
        "publication": publication,
        "file_count": len(manifest_entries),
        "files": manifest_entries,
    }
    manifest_sha = hashlib.sha256(
        json.dumps(manifest_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    manifest = {**manifest_payload, "manifest_sha256": manifest_sha}
    manifest_path = output / "static-export-manifest.json"
    _write_public_file(
        manifest_path, (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    )
    return StaticExport(
        output_dir=output,
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha,
        file_count=len(manifest_entries),
    )


def _write_public_file(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    temporary.chmod(0o644)
    os.replace(temporary, path)
