from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from socialoperator.knowledge.publication import verify_public_snapshot


@dataclass(frozen=True, slots=True)
class PortfolioSection:
    slug: str
    label: str
    description: str
    item_types: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PortfolioSectionPayload:
    slug: str
    label: str
    description: str
    entries: list[dict[str, Any]]


PORTFOLIO_SECTIONS = (
    PortfolioSection(
        slug="profile",
        label="Profile",
        description="Approved public profile summaries and biographical context.",
        item_types=("profile", "about"),
    ),
    PortfolioSection(
        slug="projects",
        label="Projects",
        description="Approved public projects owned, created, or directly authored by the user.",
        item_types=("project", "projects"),
    ),
    PortfolioSection(
        slug="works",
        label="Works",
        description=(
            "Approved public creative works, articles, publications, and portfolio artifacts."
        ),
        item_types=("work", "works", "creative_work", "article", "publication", "writing"),
    ),
    PortfolioSection(
        slug="timeline",
        label="Timeline",
        description="Approved public milestones, experience, and dated portfolio history.",
        item_types=("timeline", "milestone", "experience"),
    ),
    PortfolioSection(
        slug="skills",
        label="Skills",
        description="Approved public skills, tools, technologies, and capabilities.",
        item_types=("skill", "skills", "technology", "tool"),
    ),
    PortfolioSection(
        slug="other",
        label="Other",
        description="Approved public records that do not yet map to a primary portfolio section.",
        item_types=(),
    ),
)
SECTION_BY_SLUG = {section.slug: section for section in PORTFOLIO_SECTIONS}
KNOWN_SECTION_ITEM_TYPES = {
    item_type for section in PORTFOLIO_SECTIONS for item_type in section.item_types
}


class SnapshotRepository:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        verify_public_snapshot(self.path)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        return connection

    def publication(self) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM publication").fetchone()
        return dict(row)

    def list_items(self, *, item_types: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
        with self.connect() as connection:
            if item_types is not None:
                if not item_types:
                    rows = connection.execute(
                        """
                        SELECT * FROM portfolio_items
                        WHERE item_type NOT IN (
                            SELECT value FROM json_each(?)
                        )
                        ORDER BY title, slug
                        """,
                        (json.dumps(sorted(KNOWN_SECTION_ITEM_TYPES)),),
                    ).fetchall()
                    return [dict(row) for row in rows]
                placeholders = ",".join("?" for _ in item_types)
                rows = connection.execute(
                    f"""
                    SELECT * FROM portfolio_items
                    WHERE item_type IN ({placeholders})
                    ORDER BY title, slug
                    """,
                    item_types,
                ).fetchall()
                return [dict(row) for row in rows]
            rows = connection.execute(
                "SELECT * FROM portfolio_items ORDER BY title, slug"
            ).fetchall()
        return [dict(row) for row in rows]

    def list_section_items(self, section: PortfolioSection) -> list[dict[str, Any]]:
        return self.list_items(item_types=section.item_types)

    def get_item(self, slug: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM portfolio_items WHERE slug = ?",
                (slug,),
            ).fetchone()
        return dict(row) if row else None

    def get_item_assets(self, slug: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM portfolio_assets
                WHERE item_slug = ?
                ORDER BY source_label, public_relative_path
                """,
                (slug,),
            ).fetchall()
        return [dict(row) for row in rows]


def portfolio_template_dir() -> Path:
    packaged_templates = Path(__file__).resolve().parent / "templates"
    source_templates = Path(__file__).resolve().parents[3] / "templates" / "portfolio"
    return packaged_templates if packaged_templates.is_dir() else source_templates


def create_portfolio_app(snapshot_path: str | Path) -> FastAPI:
    repository = SnapshotRepository(snapshot_path)
    templates = Jinja2Templates(directory=str(portfolio_template_dir()))
    app = FastAPI(title="SocialOperator Portfolio", docs_url=None, redoc_url=None)
    asset_dir = repository.path.parent / "assets"
    if asset_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(asset_dir), html=False), name="assets")

    @app.get("/health")
    def health() -> dict[str, object]:
        publication = repository.publication()
        return {
            "ok": True,
            "version_number": publication["version_number"],
            "manifest_sha256": publication["manifest_sha256"],
            "item_count": publication["item_count"],
        }

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        items = repository.list_items()
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "publication": repository.publication(),
                "items": items,
                "sections": build_section_payloads(items),
                "section_nav": PORTFOLIO_SECTIONS,
                "page_title": "Profile Portfolio",
                "description": "Verified public portfolio generated from approved data.",
                "structured_data": json.dumps(
                    _collection_structured_data(items),
                    sort_keys=True,
                ),
            },
        )

    @app.get("/{section_slug}", response_class=HTMLResponse)
    def section(request: Request, section_slug: str) -> HTMLResponse:
        section_config = SECTION_BY_SLUG.get(section_slug)
        if section_config is None:
            raise HTTPException(status_code=404, detail="portfolio section not found")
        items = repository.list_section_items(section_config)
        return templates.TemplateResponse(
            request=request,
            name="section.html",
            context={
                "publication": repository.publication(),
                "section": section_config,
                "items": items,
                "section_nav": PORTFOLIO_SECTIONS,
                "page_title": section_config.label,
                "description": section_config.description,
                "structured_data": json.dumps(
                    _section_structured_data(section_config, items),
                    sort_keys=True,
                ),
            },
        )

    @app.get("/items/{slug}", response_class=HTMLResponse)
    def item(request: Request, slug: str) -> HTMLResponse:
        portfolio_item = repository.get_item(slug)
        if portfolio_item is None:
            raise HTTPException(status_code=404, detail="portfolio item not found")
        return templates.TemplateResponse(
            request=request,
            name="item.html",
            context={
                "publication": repository.publication(),
                "item": portfolio_item,
                "assets": repository.get_item_assets(slug),
                "section_nav": PORTFOLIO_SECTIONS,
                "section": section_for_item_type(str(portfolio_item["item_type"])),
                "page_title": portfolio_item["title"],
                "description": portfolio_item["summary"],
                "structured_data": json.dumps(
                    _item_structured_data(portfolio_item),
                    sort_keys=True,
                ),
            },
        )

    return app


def section_for_item_type(item_type: str) -> PortfolioSection:
    normalized = item_type.strip().lower()
    for section in PORTFOLIO_SECTIONS:
        if normalized in section.item_types:
            return section
    return SECTION_BY_SLUG["other"]


def build_section_payloads(items: list[dict[str, Any]]) -> list[PortfolioSectionPayload]:
    payloads = [
        PortfolioSectionPayload(
            slug=section.slug,
            label=section.label,
            description=section.description,
            entries=[],
        )
        for section in PORTFOLIO_SECTIONS
    ]
    by_slug = {payload.slug: payload for payload in payloads}
    for item in items:
        section = section_for_item_type(str(item["item_type"]))
        by_slug[section.slug].entries.append(item)
    return payloads


def _collection_structured_data(items: list[dict[str, Any]]) -> dict[str, object]:
    return {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": "Profile Portfolio",
        "hasPart": [
            {"@type": "CreativeWork", "name": item["title"], "url": f"/items/{item['slug']}/"}
            for item in items
        ],
    }


def _section_structured_data(
    section: PortfolioSection,
    items: list[dict[str, Any]],
) -> dict[str, object]:
    return {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": section.label,
        "description": section.description,
        "hasPart": [
            {"@type": "CreativeWork", "name": item["title"], "url": f"/items/{item['slug']}/"}
            for item in items
        ],
    }


def _item_structured_data(item: dict[str, Any]) -> dict[str, object]:
    return {
        "@context": "https://schema.org",
        "@type": "CreativeWork",
        "name": item["title"],
        "description": item["summary"],
        "dateModified": item["updated_at"],
    }
