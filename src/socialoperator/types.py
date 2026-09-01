from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import NewType

SessionId = NewType("SessionId", str)
PageId = NewType("PageId", str)
CaptureId = NewType("CaptureId", str)
ObservationId = NewType("ObservationId", str)
TargetId = NewType("TargetId", str)
ActionId = NewType("ActionId", str)
EntityId = NewType("EntityId", str)
ClaimId = NewType("ClaimId", str)
ReviewId = NewType("ReviewId", str)
PublicationId = NewType("PublicationId", str)


class CoordinateSpace(StrEnum):
    DESKTOP = "desktop"
    WINDOW = "window"
    VIEWPORT = "viewport"
    SCREENSHOT = "screenshot"
    DEVICE_PIXEL = "device_pixel"


class ActionRisk(StrEnum):
    OBSERVE = "A0"
    NAVIGATE = "A1"
    BOUNDARY = "A2"
    EXTERNAL_EFFECT = "A3"
    DESTRUCTIVE_SECURITY = "A4"


class OwnershipClass(StrEnum):
    CREATED_BY_USER = "created_by_user"
    OWNED_BY_USER = "owned_by_user"
    ABOUT_USER = "about_user"
    AUTHORIZED_ACCOUNT_EXPORT = "authorized_account_export"
    THIRD_PARTY_REFERENCE = "third_party_reference"
    UNCERTAIN = "uncertain"
    EXCLUDED = "excluded"


class Sensitivity(StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"
    RESTRICTED = "restricted"
    AUTHENTICATION = "authentication"


class ReviewStatus(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    REDACTED = "redacted"
    SUPERSEDED = "superseded"
    DEFERRED = "deferred"


class PublicationStatus(StrEnum):
    UNPUBLISHED = "unpublished"
    CANDIDATE = "candidate"
    PUBLISHED = "published"
    SUPERSEDED = "superseded"
    REVOKED = "revoked"


class OperatorState(StrEnum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    READY = "READY"
    OBSERVING = "OBSERVING"
    PLANNING_ACTION = "PLANNING_ACTION"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    MOVING_POINTER = "MOVING_POINTER"
    VERIFYING_HOVER = "VERIFYING_HOVER"
    CLICKING = "CLICKING"
    SCROLLING = "SCROLLING"
    VERIFYING_RESULT = "VERIFYING_RESULT"
    PAUSED = "PAUSED"
    PAUSED_RECOVERY = "PAUSED_RECOVERY"
    HALTED = "HALTED"


@dataclass(frozen=True, slots=True)
class Point:
    x: float
    y: float
    space: CoordinateSpace


@dataclass(frozen=True, slots=True)
class Rect:
    x: float
    y: float
    width: float
    height: float
    space: CoordinateSpace

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("rectangle width and height must be positive")

    @property
    def center(self) -> Point:
        return Point(
            x=self.x + self.width / 2,
            y=self.y + self.height / 2,
            space=self.space,
        )

    def contains(self, point: Point) -> bool:
        if point.space is not self.space:
            raise ValueError("point and rectangle must use the same coordinate space")
        return (
            self.x <= point.x <= self.x + self.width and self.y <= point.y <= self.y + self.height
        )

    def translate(self, dx: float, dy: float, *, space: CoordinateSpace | None = None) -> Rect:
        return Rect(
            x=self.x + dx,
            y=self.y + dy,
            width=self.width,
            height=self.height,
            space=space or self.space,
        )

    def scale(self, factor: float, *, space: CoordinateSpace | None = None) -> Rect:
        if factor <= 0:
            raise ValueError("scale factor must be positive")
        return Rect(
            x=self.x * factor,
            y=self.y * factor,
            width=self.width * factor,
            height=self.height * factor,
            space=space or self.space,
        )
