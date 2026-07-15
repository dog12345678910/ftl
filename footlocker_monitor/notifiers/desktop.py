"""Best-effort native desktop notifications.

Uses ``plyer`` if installed, otherwise falls back to platform CLIs
(``notify-send`` on Linux, ``osascript`` on macOS). If none are available it
degrades gracefully to a no-op so the monitor keeps running headless.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys

from .base import Notifier
from ..state import RestockEvent

log = logging.getLogger(__name__)


class DesktopNotifier(Notifier):
    def __init__(self, app_name: str = "Foot Locker Monitor") -> None:
        self.app_name = app_name

    def notify(self, event: RestockEvent) -> None:
        title = self.format_title(event)
        body = self.format_body(event)
        if self._try_plyer(title, body):
            return
        if self._try_platform_cli(title, body):
            return
        log.debug("No desktop notification backend available; skipping.")

    def _try_plyer(self, title: str, body: str) -> bool:
        try:
            from plyer import notification  # type: ignore

            notification.notify(title=title, message=body, app_name=self.app_name, timeout=10)
            return True
        except Exception:  # noqa: BLE001 - optional dependency / display errors
            return False

    def _try_platform_cli(self, title: str, body: str) -> bool:
        try:
            if sys.platform == "darwin":
                script = f'display notification {body!r} with title {title!r}'
                subprocess.run(["osascript", "-e", script], check=False, timeout=10)
                return True
            if sys.platform.startswith("linux") and shutil.which("notify-send"):
                subprocess.run(["notify-send", title, body], check=False, timeout=10)
                return True
        except Exception as exc:  # noqa: BLE001
            log.debug("Desktop CLI notification failed: %s", exc)
        return False
