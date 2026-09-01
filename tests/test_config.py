from pathlib import Path

import pytest

from socialoperator.config import (
    load_config,
    load_site_policy,
    site_policy_payload,
    site_policy_sha256,
)
from socialoperator.types import ActionRisk

ROOT = Path(__file__).resolve().parents[1]


def test_default_config_is_fail_closed() -> None:
    config = load_config(ROOT / "config" / "default.toml")
    assert config.capture.pointer_crop_size == 400
    assert not config.security.allow_real_site_capture
    assert not config.security.allow_external_side_effects
    assert config.security.require_application_encryption_for_real_data


def test_local_fixture_policy_allows_only_read_actions() -> None:
    policy = load_site_policy(ROOT / "config" / "sites" / "local_fixture.toml")
    assert policy.allowed_actions == (ActionRisk.OBSERVE, ActionRisk.NAVIGATE)
    assert not policy.real_site


def test_real_site_policy_loads_but_requires_explicit_runtime_gates() -> None:
    policy = load_site_policy(ROOT / "config" / "sites" / "real_site.example.toml")

    assert policy.real_site
    assert policy.allowed_actions == (ActionRisk.OBSERVE, ActionRisk.NAVIGATE)
    assert policy.domains == ("profile.example.com",)
    assert site_policy_payload(policy)["real_site"] is True
    assert len(site_policy_sha256(policy)) == 64


def test_site_policy_rejects_wildcard_domains(tmp_path: Path) -> None:
    path = tmp_path / "bad-site.toml"
    path.write_text(
        """
site_id = "bad"
domains = ["*.example.com"]
allowed_path_prefixes = ["/"]
account_identifiers = ["user"]
allowed_actions = ["A0"]
maximum_requests_per_minute = 30
real_site = true
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="explicit hosts"):
        load_site_policy(path)


def test_unknown_config_key_is_rejected(tmp_path: Path) -> None:
    source = (ROOT / "config" / "default.toml").read_text()
    path = tmp_path / "bad.toml"
    path.write_text(source + "\n[unknown]\nvalue = true\n")
    with pytest.raises(ValueError, match="unknown top-level"):
        load_config(path)
