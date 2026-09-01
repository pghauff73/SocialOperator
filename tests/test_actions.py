from __future__ import annotations

import json
from dataclasses import asdict

from socialoperator.browser.actions import Postcondition, observation_sha256
from socialoperator.browser.models import InteractiveTarget, PageObservation
from socialoperator.types import CoordinateSpace, Rect


def test_observation_hash_changes_with_page_state() -> None:
    target = InteractiveTarget(
        target_id="target",
        role="button",
        accessible_name="Open",
        text="Open",
        href=None,
        enabled=True,
        visible=True,
        rect=Rect(1, 2, 30, 20, CoordinateSpace.VIEWPORT),
    )
    base = PageObservation(
        url="http://127.0.0.1/",
        title="Fixture",
        captured_at="ignored",
        viewport_width=100,
        viewport_height=100,
        device_scale_factor=1,
        scroll_x=0,
        scroll_y=0,
        headings=("Fixture",),
        readable_text="Fixture Open",
        aria_snapshot='- button "Open"',
        targets=(target,),
    )
    changed = PageObservation(**{**asdict(base), "title": "Changed", "targets": (target,)})
    assert observation_sha256(base) != observation_sha256(changed)


def test_postcondition_factories() -> None:
    assert Postcondition.selector_visible("#modal") == Postcondition("selector_visible", "#modal")
    assert Postcondition.url_changed("before") == Postcondition("url_changed", "before")
    assert Postcondition.title_equals("Title") == Postcondition("title_equals", "Title")
    assert Postcondition.text_visible("Done") == Postcondition("text_visible", "Done")
    assert Postcondition.selector_hidden("#modal") == Postcondition("selector_hidden", "#modal")
    assert Postcondition.url_equals("https://example.test/") == Postcondition(
        "url_equals", "https://example.test/"
    )
    assert Postcondition.popup_url_equals("https://example.test/popup") == Postcondition(
        "popup_url_equals", "https://example.test/popup"
    )
    assert Postcondition.download_filename_equals("example.txt") == Postcondition(
        "download_filename_equals", "example.txt"
    )
    assert Postcondition.scroll_y_changed(0) == Postcondition("scroll_y_changed", "0")
    selector_text_equals = Postcondition.selector_text_equals("#page", "Page 2")
    assert selector_text_equals.kind == "selector_text_equals"
    assert json.loads(selector_text_equals.value) == {
        "expected_text": "Page 2",
        "selector": "#page",
    }
    selector_text_changed = Postcondition.selector_text_changed("#page", "Page 1")
    assert selector_text_changed.kind == "selector_text_changed"
    assert json.loads(selector_text_changed.value) == {
        "previous_text": "Page 1",
        "selector": "#page",
    }
