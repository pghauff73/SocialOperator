from __future__ import annotations

from dataclasses import dataclass

from socialoperator.config import AppConfig, SitePolicy
from socialoperator.types import ActionRisk


@dataclass(frozen=True, slots=True)
class ActionAuthorization:
    allowed: bool
    requires_approval: bool
    reason: str


def authorize_action(
    risk: ActionRisk,
    *,
    config: AppConfig,
    site_policy: SitePolicy,
) -> ActionAuthorization:
    if risk is ActionRisk.DESTRUCTIVE_SECURITY:
        return ActionAuthorization(
            False, False, "destructive and security actions are always blocked"
        )
    if risk is ActionRisk.EXTERNAL_EFFECT:
        return ActionAuthorization(
            False,
            False,
            "external side effects are blocked in the initial release",
        )
    if risk is ActionRisk.BOUNDARY:
        return ActionAuthorization(False, True, "boundary actions require explicit user approval")
    if risk not in site_policy.allowed_actions:
        return ActionAuthorization(False, False, "action is not allowed by the site policy")
    if risk is ActionRisk.NAVIGATE and config.browser.maximum_read_only_retries < 0:
        return ActionAuthorization(False, False, "invalid retry policy")
    return ActionAuthorization(True, False, "read-only action allowed by policy")
