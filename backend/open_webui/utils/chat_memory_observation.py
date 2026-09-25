from __future__ import annotations

import re
import threading
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Callable


_ERROR_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,95}$")
_DISPOSITIONS = frozenset({
    "ACCEPTED", "DUPLICATE", "RECONCILIATION_REQUIRED", "STALE_BRANCH", "TOMBSTONED",
})


class ObservationStatusRegistry:
    """Bounded volatile status for one authenticated owner/chat pair."""

    def __init__(self, maximum: int = 256, now: Callable[[], datetime] | None = None) -> None:
        if maximum < 1:
            raise ValueError("maximum must be positive")
        self.maximum = maximum
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._values: OrderedDict[tuple[str, str], dict[str, str | None]] = OrderedDict()
        self._lock = threading.Lock()

    def _timestamp(self) -> str:
        return self._now().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    def _put(self, owner_id: str, chat_id: str, value: dict[str, str | None]) -> None:
        key = (owner_id, chat_id)
        with self._lock:
            self._values.pop(key, None)
            self._values[key] = value
            while len(self._values) > self.maximum:
                self._values.popitem(last=False)

    def succeeded(self, owner_id: str, chat_id: str, disposition: object) -> None:
        normalized = str(disposition or "ACCEPTED").upper()
        if normalized not in _DISPOSITIONS:
            normalized = "ACCEPTED"
        self._put(owner_id, chat_id, {
            "state": "SUCCEEDED", "disposition": normalized,
            "error_class": None, "updated_at": self._timestamp(),
        })

    def failed(self, owner_id: str, chat_id: str, error_class: object) -> str:
        normalized = str(error_class or "INTERNAL_ERROR").upper()
        if not _ERROR_CODE.fullmatch(normalized):
            normalized = "INTERNAL_ERROR"
        self._put(owner_id, chat_id, {
            "state": "FAILED", "disposition": None,
            "error_class": normalized, "updated_at": self._timestamp(),
        })
        return normalized

    def get(self, owner_id: str, chat_id: str) -> dict[str, str | None]:
        key = (owner_id, chat_id)
        with self._lock:
            value = self._values.get(key)
            if value is None:
                return {"state": "UNKNOWN", "disposition": None, "error_class": None, "updated_at": None}
            self._values.move_to_end(key)
            return dict(value)
