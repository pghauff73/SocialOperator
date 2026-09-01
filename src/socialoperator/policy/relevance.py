from __future__ import annotations

import re
from dataclasses import dataclass

from socialoperator.config import SitePolicy
from socialoperator.types import OwnershipClass, Sensitivity


@dataclass(frozen=True, slots=True)
class ScopeDecision:
    ownership_class: OwnershipClass
    sensitivity: Sensitivity
    accepted_for_private_knowledge: bool
    eligible_for_portfolio_review: bool
    confidence: float
    reasons: tuple[str, ...]


def _normalize(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


class ScopeClassifier:
    EXCLUSION_PHRASES = (
        "sponsored",
        "advertisement",
        "recommended for you",
        "people you may know",
    )
    THIRD_PARTY_PHRASES = (
        "commented by",
        "reviewed by",
        "message from",
        "private message",
    )

    def classify(self, text: str, policy: SitePolicy) -> ScopeDecision:
        normalized = _normalize(text)
        if any(phrase in normalized for phrase in self.EXCLUSION_PHRASES):
            return ScopeDecision(
                ownership_class=OwnershipClass.EXCLUDED,
                sensitivity=Sensitivity.PRIVATE,
                accepted_for_private_knowledge=False,
                eligible_for_portfolio_review=False,
                confidence=1.0,
                reasons=("excluded content category",),
            )
        if any(phrase in normalized for phrase in self.THIRD_PARTY_PHRASES):
            return ScopeDecision(
                ownership_class=OwnershipClass.THIRD_PARTY_REFERENCE,
                sensitivity=Sensitivity.PRIVATE,
                accepted_for_private_knowledge=False,
                eligible_for_portfolio_review=False,
                confidence=0.95,
                reasons=("third-party private or authored content",),
            )
        matched_identifiers = tuple(
            identifier
            for identifier in policy.account_identifiers
            if _normalize(identifier) and _normalize(identifier) in normalized
        )
        if matched_identifiers and "created by" in normalized:
            return ScopeDecision(
                ownership_class=OwnershipClass.CREATED_BY_USER,
                sensitivity=Sensitivity.PUBLIC if not policy.real_site else Sensitivity.PRIVATE,
                accepted_for_private_knowledge=True,
                eligible_for_portfolio_review=True,
                confidence=0.98,
                reasons=(
                    f"matched account identifier: {matched_identifiers[0]}",
                    "created-by phrase",
                ),
            )
        if "user owned" in normalized or "user-owned" in text.lower():
            return ScopeDecision(
                ownership_class=OwnershipClass.OWNED_BY_USER,
                sensitivity=Sensitivity.PUBLIC if not policy.real_site else Sensitivity.PRIVATE,
                accepted_for_private_knowledge=True,
                eligible_for_portfolio_review=True,
                confidence=0.90,
                reasons=("explicit user-owned phrase",),
            )
        if matched_identifiers:
            return ScopeDecision(
                ownership_class=OwnershipClass.ABOUT_USER,
                sensitivity=Sensitivity.PUBLIC if not policy.real_site else Sensitivity.PRIVATE,
                accepted_for_private_knowledge=True,
                eligible_for_portfolio_review=True,
                confidence=0.80,
                reasons=(f"matched account identifier: {matched_identifiers[0]}",),
            )
        return ScopeDecision(
            ownership_class=OwnershipClass.UNCERTAIN,
            sensitivity=Sensitivity.PRIVATE,
            accepted_for_private_knowledge=False,
            eligible_for_portfolio_review=False,
            confidence=0.0,
            reasons=("no deterministic ownership evidence",),
        )
