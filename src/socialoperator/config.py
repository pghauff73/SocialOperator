from __future__ import annotations

import hashlib
import json
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

from socialoperator.types import ActionRisk


@dataclass(frozen=True, slots=True)
class ProjectConfig:
    name: str = "SocialOperator"
    environment: str = "development"


@dataclass(frozen=True, slots=True)
class PathsConfig:
    private_data_dir: str = "data/private"
    public_data_dir: str = "data/public"
    runtime_dir: str = "data/runtime"
    artifact_dir: str = "data/private/artifacts"
    database_path: str = "data/private/socialoperator.sqlite"
    browser_profile_dir: str = "data/private/browser-profile"
    reports_dir: str = "reports"


@dataclass(frozen=True, slots=True)
class BrowserConfig:
    headless: bool = False
    browser_name: str = "chromium"
    channel: str = ""
    default_viewport_width: int = 1440
    default_viewport_height: int = 1000
    action_timeout_seconds: float = 10.0
    maximum_read_only_retries: int = 2


@dataclass(frozen=True, slots=True)
class CaptureConfig:
    pointer_crop_size: int = 400
    full_viewport_ocr_timeout_seconds: float = 3.0
    pointer_ocr_timeout_seconds: float = 0.5
    capture_authentication: bool = False
    redact_operator_windows: bool = True


@dataclass(frozen=True, slots=True)
class SecurityConfig:
    allow_real_site_capture: bool = False
    allow_external_side_effects: bool = False
    require_application_encryption_for_real_data: bool = True
    private_directory_mode: str = "0700"
    private_file_mode: str = "0600"


@dataclass(frozen=True, slots=True)
class LimitsConfig:
    maximum_pages_per_session: int = 25
    maximum_actions_per_session: int = 100
    maximum_session_minutes: int = 30
    maximum_capture_bytes: int = 268_435_456


@dataclass(frozen=True, slots=True)
class AppConfig:
    project: ProjectConfig
    paths: PathsConfig
    browser: BrowserConfig
    capture: CaptureConfig
    security: SecurityConfig
    limits: LimitsConfig
    source_path: Path

    def resolve_path(self, value: str, *, workspace: Path | None = None) -> Path:
        path = Path(value).expanduser()
        if path.is_absolute():
            return path
        root = workspace or self.source_path.parent.parent
        return (root / path).resolve()


@dataclass(frozen=True, slots=True)
class SitePolicy:
    site_id: str
    domains: tuple[str, ...]
    allowed_path_prefixes: tuple[str, ...]
    account_identifiers: tuple[str, ...]
    allowed_actions: tuple[ActionRisk, ...]
    maximum_requests_per_minute: int
    real_site: bool
    source_path: Path


def site_policy_payload(policy: SitePolicy) -> dict[str, object]:
    return {
        "site_id": policy.site_id,
        "domains": policy.domains,
        "allowed_path_prefixes": policy.allowed_path_prefixes,
        "account_identifiers": policy.account_identifiers,
        "allowed_actions": tuple(action.value for action in policy.allowed_actions),
        "maximum_requests_per_minute": policy.maximum_requests_per_minute,
        "real_site": policy.real_site,
    }


def site_policy_sha256(policy: SitePolicy) -> str:
    encoded = json.dumps(
        site_policy_payload(policy),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _known_keys(model: type[Any]) -> set[str]:
    return {field.name for field in fields(model)}


def _build_section[T](model: type[T], values: object, section_name: str) -> T:
    if not isinstance(values, dict):
        raise ValueError(f"configuration section {section_name!r} must be a table")
    unknown = set(values) - _known_keys(model)
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ValueError(f"unknown keys in configuration section {section_name!r}: {names}")
    return model(**values)


def load_config(path: str | Path = "config/default.toml") -> AppConfig:
    source_path = Path(path).expanduser().resolve()
    with source_path.open("rb") as handle:
        raw = tomllib.load(handle)
    expected = {"project", "paths", "browser", "capture", "security", "limits"}
    unknown = set(raw) - expected
    missing = expected - set(raw)
    if unknown:
        raise ValueError(f"unknown top-level configuration keys: {', '.join(sorted(unknown))}")
    if missing:
        raise ValueError(f"missing configuration sections: {', '.join(sorted(missing))}")
    config = AppConfig(
        project=_build_section(ProjectConfig, raw["project"], "project"),
        paths=_build_section(PathsConfig, raw["paths"], "paths"),
        browser=_build_section(BrowserConfig, raw["browser"], "browser"),
        capture=_build_section(CaptureConfig, raw["capture"], "capture"),
        security=_build_section(SecurityConfig, raw["security"], "security"),
        limits=_build_section(LimitsConfig, raw["limits"], "limits"),
        source_path=source_path,
    )
    _validate_config(config)
    return config


def _validate_config(config: AppConfig) -> None:
    if config.capture.pointer_crop_size <= 0 or config.capture.pointer_crop_size % 2:
        raise ValueError("pointer_crop_size must be a positive even integer")
    if config.browser.maximum_read_only_retries < 0:
        raise ValueError("maximum_read_only_retries cannot be negative")
    if config.security.allow_external_side_effects:
        raise ValueError("external side effects are blocked in the initial release")
    if (
        config.security.allow_real_site_capture
        and config.security.require_application_encryption_for_real_data
    ):
        raise ValueError(
            "real-site capture cannot be enabled until application-level encryption is implemented"
        )


def load_site_policy(path: str | Path) -> SitePolicy:
    source_path = Path(path).expanduser().resolve()
    with source_path.open("rb") as handle:
        raw = tomllib.load(handle)
    expected = {
        "site_id",
        "domains",
        "allowed_path_prefixes",
        "account_identifiers",
        "allowed_actions",
        "maximum_requests_per_minute",
        "real_site",
    }
    unknown = set(raw) - expected
    missing = expected - set(raw)
    if unknown:
        raise ValueError(f"unknown site-policy keys: {', '.join(sorted(unknown))}")
    if missing:
        raise ValueError(f"missing site-policy keys: {', '.join(sorted(missing))}")
    actions = tuple(ActionRisk(value) for value in raw["allowed_actions"])
    if any(action not in {ActionRisk.OBSERVE, ActionRisk.NAVIGATE} for action in actions):
        raise ValueError("initial site policies may allow only A0 and A1 actions")
    policy = SitePolicy(
        site_id=str(raw["site_id"]),
        domains=tuple(str(value).lower() for value in raw["domains"]),
        allowed_path_prefixes=tuple(str(value) for value in raw["allowed_path_prefixes"]),
        account_identifiers=tuple(str(value) for value in raw["account_identifiers"]),
        allowed_actions=actions,
        maximum_requests_per_minute=int(raw["maximum_requests_per_minute"]),
        real_site=bool(raw["real_site"]),
        source_path=source_path,
    )
    _validate_site_policy(policy)
    return policy


def _validate_site_policy(policy: SitePolicy) -> None:
    if not policy.site_id.strip():
        raise ValueError("site_id cannot be empty")
    if not policy.domains:
        raise ValueError("site policy must define at least one domain")
    if any(domain in {"*", ""} or "*" in domain for domain in policy.domains):
        raise ValueError("site-policy domains must be explicit hosts")
    if not policy.allowed_path_prefixes:
        raise ValueError("site policy must define at least one path prefix")
    if any(not prefix.startswith("/") for prefix in policy.allowed_path_prefixes):
        raise ValueError("site-policy path prefixes must start with /")
    if not policy.account_identifiers:
        raise ValueError("site policy must define at least one account identifier")
    if not policy.allowed_actions:
        raise ValueError("site policy must define at least one allowed action")
    if policy.maximum_requests_per_minute <= 0:
        raise ValueError("maximum_requests_per_minute must be positive")


def ensure_runtime_directories(config: AppConfig, *, workspace: Path | None = None) -> None:
    mode = int(config.security.private_directory_mode, 8)
    directories = (
        config.paths.private_data_dir,
        config.paths.public_data_dir,
        config.paths.runtime_dir,
        config.paths.artifact_dir,
        config.paths.browser_profile_dir,
        config.paths.reports_dir,
    )
    for value in directories:
        directory = config.resolve_path(value, workspace=workspace)
        directory.mkdir(parents=True, exist_ok=True)
        if value in {
            config.paths.private_data_dir,
            config.paths.artifact_dir,
            config.paths.browser_profile_dir,
        }:
            directory.chmod(mode)
