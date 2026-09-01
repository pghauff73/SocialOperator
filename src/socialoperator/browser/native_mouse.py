from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from socialoperator.types import CoordinateSpace, Point, Rect


class NativeMouse(Protocol):
    def move_to(self, x: float, y: float, duration_seconds: float) -> None: ...

    def position(self) -> Point: ...

    def click(self) -> None: ...

    def scroll(self, amount: int) -> None: ...


class PyAutoGuiMouse:
    def __init__(self) -> None:
        import pyautogui

        pyautogui.FAILSAFE = True
        self._pyautogui = pyautogui

    def move_to(self, x: float, y: float, duration_seconds: float) -> None:
        self._pyautogui.moveTo(x, y, duration=max(duration_seconds, 0))

    def position(self) -> Point:
        position = self._pyautogui.position()
        return Point(float(position.x), float(position.y), CoordinateSpace.DESKTOP)

    def click(self) -> None:
        self._pyautogui.click()

    def scroll(self, amount: int) -> None:
        self._pyautogui.scroll(amount)


class MouseSafetyError(RuntimeError):
    """Raised when native pointer safety checks fail."""


@dataclass(slots=True)
class MouseSafetyController:
    mouse: NativeMouse
    foreground_check: Callable[[], bool]
    movement_duration_seconds: float = 0.25

    def move_to_target(self, target: Rect) -> Point:
        if target.space is not CoordinateSpace.DESKTOP:
            raise MouseSafetyError("native mouse targets must use desktop coordinates")
        if not self.foreground_check():
            raise MouseSafetyError("dedicated browser is not the verified foreground window")
        center = target.center
        self.mouse.move_to(center.x, center.y, self.movement_duration_seconds)
        actual = self.mouse.position()
        if not target.contains(actual):
            raise MouseSafetyError("pointer did not arrive inside the target bounds")
        if not self.foreground_check():
            raise MouseSafetyError("foreground window changed during pointer movement")
        return actual

    def click_target(self, target: Rect) -> Point:
        actual = self.move_to_target(target)
        self.mouse.click()
        return actual

    def scroll_current(self, amount: int) -> Point:
        if not self.foreground_check():
            raise MouseSafetyError("dedicated browser is not the verified foreground window")
        self.mouse.scroll(amount)
        actual = self.mouse.position()
        if not self.foreground_check():
            raise MouseSafetyError("foreground window changed during scroll")
        return actual
