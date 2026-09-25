"""Phase 5H H1 (adapter side) — receive an evaluation-completion push and publish it.

The Chat Memory Core pushes a bounded, content-free record when a round's evaluation reaches a
terminal state. This module owns the two halves the adapter needs:

1. **the shared secret.** Production runs the Core in client-API mode, where it holds no Open WebUI
   credential, so the callback runs server-to-server with a secret this process owns: a 32-byte
   random token in `~/open-webui/data/chat-memory-callback.token`, mode 600, created atomically on
   first use. The Core reads the same file, lazily, so the order the two services start in does not
   matter.
2. **the publish.** One socket event (`chat_memory:evaluated`) to the owner's own room, so the HUD
   can refresh without a poll (owner decision D1) and the composer can show its held-send state
   (owner decision D3). It is display state: nothing here changes memory.

The push carries identities, a disposition and monotonic revisions only — never source prose and
never memory content, which is also what keeps the socket event safe to broadcast to a browser.
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import tempfile
from pathlib import Path


log = logging.getLogger(__name__)

# The wire contract with the Chat Memory Core. The Core keeps its own copy (it is a separate
# package and cannot import this one) and `tests/integrations/test_evaluation_push_contract.py`
# asserts the two agree, so neither side can drift silently.
#
# `CALLBACK_TOKEN_FILENAME` is also the file name the Core's `--evaluation-callback-token-file`
# default points at.
CALLBACK_TOKEN_FILENAME = "chat-memory-callback.token"
MINIMUM_TOKEN_LENGTH = 32
EVALUATION_EVENT_TYPE = "chat_memory:evaluated"

# One publish per scope revision. The Core already guarantees a strictly increasing
# `evaluation_revision`; this is the adapter's own guard against a repeated delivery of the same
# revision (a retried POST, or the same completion observed twice), so the plan's "exactly one
# socket event per committed evaluation" holds even if the push is duplicated on the wire.
_MAX_TRACKED_SCOPES = 512


class EvaluationPushRegistry:
    """Bounded last-published-revision memory, so a duplicate push is not published twice."""

    def __init__(self, maximum: int = _MAX_TRACKED_SCOPES) -> None:
        self.publish_lock = asyncio.Lock()
        self.maximum = int(maximum)
        self._last: dict[tuple[str, str], int] = {}
        self._order: list[tuple[str, str]] = []

    def accept(self, owner_id: str, chat_id: str, evaluation_revision: int) -> bool:
        key = (str(owner_id), str(chat_id))
        previous = self._last.get(key)
        if previous is not None and int(evaluation_revision) <= previous:
            return False
        if previous is None:
            self._order.append(key)
        self._last[key] = int(evaluation_revision)
        while len(self._order) > self.maximum:
            self._last.pop(self._order.pop(0), None)
        return True

    def last_revision(self, owner_id: str, chat_id: str) -> int | None:
        return self._last.get((str(owner_id), str(chat_id)))


_evaluation_pushes = EvaluationPushRegistry()


def push_registry() -> EvaluationPushRegistry:
    return _evaluation_pushes


def callback_token_path(data_root: Path | str) -> Path:
    return Path(data_root) / CALLBACK_TOKEN_FILENAME


def ensure_callback_token(data_root: Path | str) -> str:
    """Return the shared callback secret, creating it atomically when it does not exist yet.

    Written mode 600: it authorizes exactly one loopback route, and only the two services that
    already run as the same account can read it. An existing short or empty file is replaced rather
    than trusted, so a truncated write cannot silently weaken the check.
    """
    path = callback_token_path(data_root)
    try:
        existing = path.read_text(encoding="utf-8").strip()
        if len(existing) >= MINIMUM_TOKEN_LENGTH:
            return existing
    except FileNotFoundError:
        pass
    except OSError:
        pass
    token = secrets.token_hex(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=str(path.parent), prefix=".chat-memory-callback.", text=True)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(token + "\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return token


def token_matches(candidate: str, expected: str) -> bool:
    """Constant-time comparison; an absent expectation never matches."""
    if not expected or len(expected) < MINIMUM_TOKEN_LENGTH:
        return False
    return secrets.compare_digest(str(candidate or ""), expected)


async def publish_evaluation_completed(
    request_info: dict,
    *,
    owner_id: str,
    chat_id: str,
    round_id: str,
    assistant_message_id: str,
    disposition: str,
    semantic_revision: int,
    evaluation_revision: int,
    lifecycle: dict | None = None,
) -> bool:
    """Publish one `chat_memory:evaluated` event to the owner's room.

    Content-free: identities, disposition and revisions only. Returns False when the push was a
    duplicate revision, so the caller can answer *accepted but not published* honestly.
    """
    async with _evaluation_pushes.publish_lock:
        previous = _evaluation_pushes.last_revision(owner_id, chat_id)
        if previous is not None and evaluation_revision <= previous:
            return False
        from open_webui.socket.main import get_event_emitter
        emitter = await get_event_emitter(request_info, update_db=False)
        await asyncio.wait_for(emitter({
            "type": EVALUATION_EVENT_TYPE,
            "data": {
                "chat_id": str(chat_id), "round_id": str(round_id),
                "assistant_message_id": str(assistant_message_id), "disposition": str(disposition),
                "semantic_revision": int(semantic_revision), "evaluation_revision": int(evaluation_revision),
                **(lifecycle or {}),
            },
        }), timeout=2.0)
        # A failed send is retryable; only successful emits commit the dedupe revision.
        _evaluation_pushes.accept(owner_id, chat_id, evaluation_revision)
        return True
