from __future__ import annotations

import re
from dataclasses import dataclass

from socialoperator.browser.models import InteractiveTarget


class TargetSelectionError(RuntimeError):
    """Base target-selection failure."""


class TargetNotFoundError(TargetSelectionError):
    """Raised when no target has sufficient evidence."""


class AmbiguousTargetError(TargetSelectionError):
    """Raised when multiple targets remain equally plausible."""


@dataclass(frozen=True, slots=True)
class TargetCandidate:
    target: InteractiveTarget
    score: float
    reasons: tuple[str, ...]


def _normalize(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def rank_targets(
    query: str,
    targets: tuple[InteractiveTarget, ...],
    *,
    ocr_text: str = "",
) -> tuple[TargetCandidate, ...]:
    normalized_query = _normalize(query)
    query_tokens = set(normalized_query.split())
    normalized_ocr = _normalize(ocr_text)
    candidates: list[TargetCandidate] = []
    for target in targets:
        if not target.visible or not target.enabled:
            continue
        name = _normalize(target.accessible_name or target.text)
        name_tokens = set(name.split())
        reasons: list[str] = []
        score = 0.0
        if name == normalized_query and normalized_query:
            score += 0.75
            reasons.append("exact_accessible_name")
        elif normalized_query and normalized_query in name:
            score += 0.55
            reasons.append("contained_accessible_name")
        elif query_tokens:
            overlap = len(query_tokens & name_tokens) / len(query_tokens)
            score += 0.45 * overlap
            if overlap:
                reasons.append(f"name_token_overlap:{overlap:.2f}")
        if normalized_query and normalized_query in normalized_ocr:
            score += 0.15
            reasons.append("ocr_support")
        if target.role in {"button", "link"}:
            score += 0.10
            reasons.append("interactive_role")
        candidates.append(TargetCandidate(target=target, score=score, reasons=tuple(reasons)))
    return tuple(sorted(candidates, key=lambda value: (-value.score, value.target.target_id)))


def select_target(
    query: str,
    targets: tuple[InteractiveTarget, ...],
    *,
    ocr_text: str = "",
    minimum_score: float = 0.70,
    ambiguity_margin: float = 0.05,
) -> TargetCandidate:
    ranked = rank_targets(query, targets, ocr_text=ocr_text)
    if not ranked or ranked[0].score < minimum_score:
        raise TargetNotFoundError(f"no target reached the minimum score for {query!r}")
    if len(ranked) > 1 and ranked[0].score - ranked[1].score < ambiguity_margin:
        raise AmbiguousTargetError(
            f"target selection is ambiguous for {query!r}: "
            f"{ranked[0].target.accessible_name!r} and {ranked[1].target.accessible_name!r}"
        )
    return ranked[0]
