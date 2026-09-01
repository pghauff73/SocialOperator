from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path


class AccessibilityProbe(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.html_has_lang = False
        self.in_title = False
        self.title_text = ""
        self.main_count = 0
        self.nav_count = 0
        self.h1_count = 0
        self.in_link = False
        self.current_link_text = ""
        self.empty_links = 0
        self.images_without_alt = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "html" and (attributes.get("lang") or "").strip():
            self.html_has_lang = True
        if tag == "title":
            self.in_title = True
        if tag == "main":
            self.main_count += 1
        if tag == "nav":
            self.nav_count += 1
        if tag == "h1":
            self.h1_count += 1
        if tag == "a":
            self.in_link = True
            self.current_link_text = ""
        if tag == "img" and not (attributes.get("alt") or "").strip():
            self.images_without_alt += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False
        if tag == "a" and self.in_link:
            if not self.current_link_text.strip():
                self.empty_links += 1
            self.in_link = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_text += data
        if self.in_link:
            self.current_link_text += data


def check_html_accessibility(html: str, *, label: str) -> list[str]:
    probe = AccessibilityProbe()
    probe.feed(html)
    errors: list[str] = []
    if not probe.html_has_lang:
        errors.append(f"{label}: missing html lang")
    if not probe.title_text.strip():
        errors.append(f"{label}: missing title")
    if probe.main_count != 1:
        errors.append(f"{label}: expected exactly one main landmark")
    if probe.nav_count < 1:
        errors.append(f"{label}: missing navigation landmark")
    if probe.h1_count != 1:
        errors.append(f"{label}: expected exactly one h1")
    if probe.empty_links:
        errors.append(f"{label}: contains empty links")
    if probe.images_without_alt:
        errors.append(f"{label}: contains images without alt text")
    return errors


def check_static_export(output_dir: str | Path) -> list[str]:
    root = Path(output_dir).expanduser().resolve()
    errors: list[str] = []
    for html_path in sorted(root.rglob("*.html")):
        errors.extend(
            check_html_accessibility(
                html_path.read_text(encoding="utf-8"),
                label=html_path.relative_to(root).as_posix(),
            )
        )
    return errors
