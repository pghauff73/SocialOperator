from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from socialoperator.adapters.base import AdapterDisabledError, AdapterDriftError, AdapterRegistry
from socialoperator.adapters.local_fixture import create_local_fixture_adapter
from socialoperator.browser.observer import PageObserver
from socialoperator.browser.session import BrowserSession
from socialoperator.config import load_config, load_site_policy

ROOT = Path(__file__).resolve().parents[1]


def test_adapter_validates_fixture_and_halts_on_drift(
    tmp_path: Path,
    fixture_server_url: str,
) -> None:
    config = load_config(ROOT / "config" / "default.toml")
    policy = load_site_policy(ROOT / "config" / "sites" / "local_fixture.toml")
    adapter = create_local_fixture_adapter(policy)
    session = BrowserSession(
        config,
        policy,
        workspace=ROOT,
        profile_dir=tmp_path / "profile",
        headless=True,
    )
    try:
        session.start(fixture_server_url)
        session.resume_after_login()
        observation = PageObserver().observe(session)
    finally:
        session.stop()
    assert adapter.validate(observation).valid
    drifted = replace(observation, headings=("Unexpected redesign",))
    with pytest.raises(AdapterDriftError, match="missing required heading"):
        adapter.require_valid(drifted)


def test_adapter_registry_disables_after_drift() -> None:
    policy = load_site_policy(ROOT / "config" / "sites" / "local_fixture.toml")
    registry = AdapterRegistry()
    registry.register(create_local_fixture_adapter(policy))
    registry.disable("local_fixture", "required heading disappeared")
    with pytest.raises(AdapterDisabledError, match="required heading disappeared"):
        registry.get("local_fixture")
    registry.enable("local_fixture")
    assert registry.get("local_fixture").adapter_version == "1.0.0"
