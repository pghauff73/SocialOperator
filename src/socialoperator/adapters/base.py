from __future__ import annotations

from dataclasses import dataclass

from socialoperator.browser.models import PageObservation
from socialoperator.config import SitePolicy
from socialoperator.policy.domains import is_url_allowed


class AdapterError(RuntimeError):
    """Base site-adapter error."""


class AdapterDriftError(AdapterError):
    """Raised when required site invariants no longer hold."""


class AdapterDisabledError(AdapterError):
    """Raised when an adapter was disabled after drift or an incident."""


@dataclass(frozen=True, slots=True)
class AdapterValidation:
    site_id: str
    adapter_version: str
    valid: bool
    errors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DeclarativeSiteAdapter:
    policy: SitePolicy
    adapter_version: str
    required_heading_phrases: tuple[str, ...] = ()
    required_target_names: tuple[str, ...] = ()
    forbidden_text_phrases: tuple[str, ...] = ()

    def validate(self, observation: PageObservation) -> AdapterValidation:
        errors: list[str] = []
        if not is_url_allowed(observation.url, self.policy):
            errors.append("URL is outside the adapter policy")
        normalized_headings = tuple(value.casefold() for value in observation.headings)
        for phrase in self.required_heading_phrases:
            if not any(phrase.casefold() in heading for heading in normalized_headings):
                errors.append(f"missing required heading phrase: {phrase}")
        target_names = {
            (target.accessible_name or target.text).strip().casefold()
            for target in observation.targets
            if target.visible
        }
        for target_name in self.required_target_names:
            if target_name.casefold() not in target_names:
                errors.append(f"missing required target: {target_name}")
        normalized_text = observation.readable_text.casefold()
        for phrase in self.forbidden_text_phrases:
            if phrase.casefold() in normalized_text:
                errors.append(f"forbidden drift marker present: {phrase}")
        return AdapterValidation(
            site_id=self.policy.site_id,
            adapter_version=self.adapter_version,
            valid=not errors,
            errors=tuple(errors),
        )

    def require_valid(self, observation: PageObservation) -> None:
        validation = self.validate(observation)
        if not validation.valid:
            raise AdapterDriftError("; ".join(validation.errors))


class AdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, DeclarativeSiteAdapter] = {}
        self._disabled: dict[str, str] = {}

    def register(self, adapter: DeclarativeSiteAdapter) -> None:
        site_id = adapter.policy.site_id
        if site_id in self._adapters:
            raise AdapterError(f"adapter is already registered: {site_id}")
        self._adapters[site_id] = adapter

    def disable(self, site_id: str, reason: str) -> None:
        if site_id not in self._adapters:
            raise KeyError(f"unknown adapter: {site_id}")
        self._disabled[site_id] = reason

    def enable(self, site_id: str) -> None:
        if site_id not in self._adapters:
            raise KeyError(f"unknown adapter: {site_id}")
        self._disabled.pop(site_id, None)

    def get(self, site_id: str) -> DeclarativeSiteAdapter:
        if site_id in self._disabled:
            raise AdapterDisabledError(
                f"adapter {site_id!r} is disabled: {self._disabled[site_id]}"
            )
        try:
            return self._adapters[site_id]
        except KeyError as error:
            raise KeyError(f"unknown adapter: {site_id}") from error
