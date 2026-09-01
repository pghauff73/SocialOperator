from __future__ import annotations

import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass


def _default_runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=2,
    )


@dataclass(frozen=True, slots=True)
class X11ActiveWindowGuard:
    expected_title: Callable[[], str]
    browser_class_markers: tuple[str, ...] = ("google-chrome", "chromium", "chrome")
    runner: Callable[[Sequence[str]], subprocess.CompletedProcess[str]] = _default_runner

    def __call__(self) -> bool:
        try:
            active = self.runner(("xprop", "-root", "_NET_ACTIVE_WINDOW"))
        except (OSError, subprocess.SubprocessError):
            return False
        if active.returncode != 0:
            return False
        match = re.search(r"0x[0-9a-fA-F]+", active.stdout)
        if match is None or match.group(0).lower() == "0x0":
            return False
        window_id = match.group(0)
        try:
            properties = self.runner(
                ("xprop", "-id", window_id, "_NET_WM_NAME", "WM_NAME", "WM_CLASS")
            )
        except (OSError, subprocess.SubprocessError):
            return False
        if properties.returncode != 0:
            return False
        output = properties.stdout.casefold()
        title = self.expected_title().strip().casefold()
        title_matches = bool(title) and title in output
        class_matches = any(marker.casefold() in output for marker in self.browser_class_markers)
        return title_matches and class_matches
