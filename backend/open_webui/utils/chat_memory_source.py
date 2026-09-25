from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from typing import Any, Callable, Mapping


MAX_MESSAGES = 10_000
MAX_ACTIVE_LINEAGE = 10_000
MAX_MESSAGE_CHARACTERS = 256_000
MAX_TOTAL_CHARACTERS = 2_000_000
MAX_SYNC_BYTES = 1_000_000


class ChatMemoryProjectionError(ValueError):
    """The trusted Open WebUI chat cannot be projected safely."""


class ChatMemoryClientError(RuntimeError):
    """A structured failure returned by the Chat Memory client transport."""

    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


@dataclass(frozen=True)
class ProjectedChat:
    """A complete generic-source synchronization body and content-free identity."""

    body: dict[str, Any]
    projection_hash: str
    message_count: int
    active_count: int


@dataclass(frozen=True)
class SynchronizationResult:
    disposition: str
    source_revision: int
    branch_generation: int
    projection_hash: str
    message_count: int
    active_count: int


# What an admitted observation is about: the assistant identity and the projected body it
# carried. An in-place rewrite (Continue Response, an edit, a regeneration) changes the body
# while keeping the identity, so the identity alone cannot key a cached admission.
_ObservationKey = tuple[str, str]


@dataclass(frozen=True)
class _KnownProjection:
    active: tuple[tuple[str, str], ...]
    branch_generation: int
    projection_hash: str
    snapshot_hash: str | None
    message_count: int
    active_count: int


class OpenWebUIChatProjector:
    """Project one trusted Open WebUI chat through a small, deterministic interface.

    Graph traversal, completion eligibility, retrieval-feedback exclusion,
    hashing, canonical ordering, and bounds stay inside this module so Filter,
    Event, Tool, and backend routes do not each reinterpret Open WebUI history.
    """

    @staticmethod
    def _text(value: Any, name: str, maximum: int) -> str:
        if not isinstance(value, str) or not value.strip() or len(value) > maximum:
            raise ChatMemoryProjectionError(f"{name} must be non-empty and bounded")
        return value

    @staticmethod
    def _active_lineage(messages: Mapping[str, Mapping[str, Any]], current_id: Any) -> tuple[str, ...]:
        if current_id is None:
            return ()
        if not isinstance(current_id, str) or not current_id:
            raise ChatMemoryProjectionError("current message identity is invalid")
        lineage: list[str] = []
        seen: set[str] = set()
        cursor: str | None = current_id
        while cursor is not None:
            if cursor in seen or cursor not in messages:
                raise ChatMemoryProjectionError("active lineage is cyclic or incomplete")
            seen.add(cursor)
            lineage.append(cursor)
            parent = messages[cursor].get("parentId")
            if parent is not None and (not isinstance(parent, str) or not parent):
                raise ChatMemoryProjectionError("parent identity is invalid")
            cursor = parent
            if len(lineage) > MAX_ACTIVE_LINEAGE:
                raise ChatMemoryProjectionError("active lineage exceeds bound")
        lineage.reverse()
        return tuple(lineage)

    @staticmethod
    def _memory_only_recall(message: Mapping[str, Any]) -> bool:
        output = message.get("output")
        if not isinstance(output, list) or len(output) > 32:
            return False
        call_ids = {
            str(item.get("call_id") or item.get("id") or "")
            for item in output
            if isinstance(item, Mapping)
            and item.get("type") == "function_call"
            and item.get("name") == "answer_from_chat_memory_v2"
        }
        call_ids.discard("")
        for item in output:
            if (
                not isinstance(item, Mapping)
                or item.get("type") != "function_call_output"
                or str(item.get("call_id") or "") not in call_ids
            ):
                continue
            parts = item.get("output")
            if not isinstance(parts, list) or len(parts) > 16:
                continue
            raw = "".join(
                str(part.get("text") or "")
                for part in parts if isinstance(part, Mapping)
            )
            if not raw or len(raw.encode("utf-8")) > 16 * 1024:
                continue
            try:
                envelope = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            if (
                isinstance(envelope, dict)
                and envelope.get("contract") == "fast-answer-tool-result-v1-isolated"
                and envelope.get("delivery_mode") == "MEMORY_ONLY"
                and str(envelope.get("publication_handle") or "").startswith(("pa1.", "pa2."))
            ):
                return True
        return False

    def complete_sync(
        self,
        chat_record: Mapping[str, Any],
        *,
        trusted_owner_id: str,
        trusted_chat_id: str,
        instance_id: str,
        operation_id: str,
        expected_source_revision: int,
        branch_generation: int,
    ) -> ProjectedChat:
        owner_id = self._text(trusted_owner_id, "owner_id", 256)
        chat_id = self._text(trusted_chat_id, "chat_id", 256)
        instance = self._text(instance_id, "instance_id", 128)
        operation = self._text(operation_id, "operation_id", 128)
        if chat_record.get("id") != chat_id or chat_record.get("user_id") != owner_id:
            raise ChatMemoryProjectionError("trusted chat identity or owner mismatch")
        if (
            not isinstance(expected_source_revision, int)
            or isinstance(expected_source_revision, bool)
            or expected_source_revision < 0
        ):
            raise ChatMemoryProjectionError("expected source revision is invalid")
        if not isinstance(branch_generation, int) or isinstance(branch_generation, bool) or branch_generation < 1:
            raise ChatMemoryProjectionError("branch generation is invalid")

        chat = chat_record.get("chat")
        history = chat.get("history") if isinstance(chat, Mapping) else None
        raw_messages = history.get("messages") if isinstance(history, Mapping) else None
        if not isinstance(raw_messages, Mapping) or len(raw_messages) > MAX_MESSAGES:
            raise ChatMemoryProjectionError("message collection is invalid or exceeds bound")

        messages: dict[str, Mapping[str, Any]] = {}
        total_characters = 0
        for key, raw_message in raw_messages.items():
            identity = self._text(key, "message_id", 256)
            if not isinstance(raw_message, Mapping) or raw_message.get("id", identity) != identity:
                raise ChatMemoryProjectionError("message identity mismatch")
            parent = raw_message.get("parentId")
            if parent is not None and (not isinstance(parent, str) or not parent or len(parent) > 256):
                raise ChatMemoryProjectionError("parent identity is invalid")
            role = raw_message.get("role")
            if not isinstance(role, str) or not role or len(role) > 32:
                raise ChatMemoryProjectionError("message role is invalid")
            content = raw_message.get("content")
            if content is None:
                content = ""
            if not isinstance(content, str) or len(content) > MAX_MESSAGE_CHARACTERS:
                raise ChatMemoryProjectionError("message content is invalid or exceeds bound")
            total_characters += len(content)
            if total_characters > MAX_TOTAL_CHARACTERS:
                raise ChatMemoryProjectionError("chat content exceeds bound")
            messages[identity] = raw_message
        if any(
            message.get("parentId") is not None and message.get("parentId") not in messages
            for message in messages.values()
        ):
            raise ChatMemoryProjectionError("message parent is absent")

        current_id = chat_record.get("current_message_id")
        if current_id is None and isinstance(history, Mapping):
            current_id = history.get("currentId")
        active = self._active_lineage(messages, current_id)
        active_positions = {identity: index for index, identity in enumerate(active)}
        memory_only = {
            identity for identity, value in messages.items()
            if self._memory_only_recall(value)
        }
        ordered_ids = active + tuple(sorted(set(messages) - set(active)))
        projected_messages: list[dict[str, Any]] = []
        for identity in ordered_ids:
            message = messages[identity]
            role = str(message["role"])
            content = message.get("content")
            if content is None:
                content = ""
            error = bool(message.get("error"))
            done = bool(message.get("done"))
            position = active_positions.get(identity)
            user_has_final = False
            if role == "user" and position is not None and position + 1 < len(active):
                successor = messages[active[position + 1]]
                user_has_final = (
                    successor.get("role") == "assistant"
                    and bool(successor.get("done"))
                    and not bool(successor.get("error"))
                )
            if error:
                completion = "FAILED"
            elif done or user_has_final:
                completion = "COMPLETE"
            else:
                completion = "INCOMPLETE"
            visible = identity in active_positions
            eligible = (
                visible
                and role in {"user", "assistant"}
                and completion == "COMPLETE"
                and (role == "assistant" or user_has_final)
                and identity not in memory_only
            )
            projected = {
                "message_id": identity,
                "parent_message_id": message.get("parentId"),
                "role": role,
                "content": content,
                "content_hash": "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "completion_state": completion,
                "evidence_eligible": eligible,
                "visible": visible,
            }
            if message.get("timestamp") is not None:
                projected["observed_at"] = str(message["timestamp"])
            projected_messages.append(projected)

        body = {
            "instance_id": instance,
            "owner_id": owner_id,
            "chat_id": chat_id,
            "operation_id": operation,
            "expected_source_revision": expected_source_revision,
            "branch_generation": branch_generation,
            "active_lineage": list(active),
            "messages": projected_messages,
        }
        encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if len(encoded) > MAX_SYNC_BYTES:
            raise ChatMemoryProjectionError("synchronization payload exceeds transport bound")
        source_projection = json.dumps(
            {
                "instance_id": instance,
                "owner_id": owner_id,
                "chat_id": chat_id,
                "active_lineage": body["active_lineage"],
                "messages": body["messages"],
            },
            sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode("utf-8")
        return ProjectedChat(
            body=body,
            projection_hash=hashlib.sha256(source_projection).hexdigest(),
            message_count=len(projected_messages),
            active_count=len(active),
        )


class OpenWebUISourceSynchronizer:
    """Converge trusted Open WebUI chats with volatile Chat Memory source state.

    The injected transport is the remote-owned seam: production supplies the
    loopback HTTP adapter and tests supply an in-memory adapter. Callers need
    only one `synchronize` operation; inventory, revision selection, branch
    advancement, deterministic operation identity, and bounded retry remain
    inside this module.
    """

    def __init__(
        self,
        instance_id: str,
        post: Callable[[str, dict[str, Any]], dict[str, Any]],
        *,
        projector: OpenWebUIChatProjector | None = None,
        lock_stripes: int = 32,
    ) -> None:
        if not isinstance(instance_id, str) or not instance_id.strip() or len(instance_id) > 128:
            raise ValueError("bounded instance identity required")
        if lock_stripes < 1 or lock_stripes > 256:
            raise ValueError("lock stripe count is invalid")
        self.instance_id = instance_id
        self._post = post
        self._projector = projector or OpenWebUIChatProjector()
        self._locks = tuple(threading.RLock() for _ in range(lock_stripes))
        self._state_lock = threading.Lock()
        self._known: dict[tuple[str, str], _KnownProjection] = {}
        self._pending_observations: dict[tuple[str, str], tuple[_ObservationKey, dict[str, Any]]] = {}
        self._last_observations: dict[tuple[str, str], tuple[_ObservationKey, dict[str, Any]]] = {}

    def _scope(self, owner_id: str, chat_id: str) -> dict[str, str]:
        return {
            "instance_id": self.instance_id,
            "owner_id": owner_id,
            "chat_id": chat_id,
        }

    def _lock(self, owner_id: str, chat_id: str) -> threading.Lock:
        digest = hashlib.sha256(f"{owner_id}\0{chat_id}".encode("utf-8")).digest()
        return self._locks[int.from_bytes(digest[:4], "big") % len(self._locks)]

    @staticmethod
    def _active_projection(projected: ProjectedChat) -> tuple[tuple[str, str], ...]:
        hashes = {
            str(message["message_id"]): str(message["content_hash"])
            for message in projected.body["messages"]
        }
        return tuple((str(identity), hashes[str(identity)]) for identity in projected.body["active_lineage"])

    @staticmethod
    def _is_append(previous: tuple[tuple[str, str], ...], current: tuple[tuple[str, str], ...]) -> bool:
        return len(current) >= len(previous) and current[:len(previous)] == previous

    @staticmethod
    def _operation_id(
        owner_id: str,
        chat_id: str,
        expected_revision: int,
        branch_generation: int,
        active: tuple[tuple[str, str], ...],
    ) -> str:
        value = json.dumps(
            [owner_id, chat_id, expected_revision, branch_generation, active],
            separators=(",", ":"), ensure_ascii=False,
        ).encode("utf-8")
        return "owui-sync-" + hashlib.sha256(value).hexdigest()[:40]

    def _inventory(self, owner_id: str, chat_id: str) -> dict[str, Any]:
        value = self._post("/v1/memory/source/inventory", self._scope(owner_id, chat_id))
        if not isinstance(value, dict):
            raise ChatMemoryClientError(503, "INVALID_INVENTORY_RESPONSE")
        if value.get("deleted") is True:
            raise ChatMemoryClientError(409, "SOURCE_STALE")
        revision = value.get("source_revision")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
            raise ChatMemoryClientError(503, "INVALID_INVENTORY_RESPONSE")
        return value

    def _project(
        self,
        chat_record: Mapping[str, Any],
        owner_id: str,
        chat_id: str,
        revision: int,
        branch: int,
        operation_id: str,
    ) -> ProjectedChat:
        return self._projector.complete_sync(
            chat_record,
            trusted_owner_id=owner_id,
            trusted_chat_id=chat_id,
            instance_id=self.instance_id,
            operation_id=operation_id,
            expected_source_revision=revision,
            branch_generation=branch,
        )

    def synchronize(
        self,
        chat_record: Mapping[str, Any],
        *,
        trusted_owner_id: str,
        trusted_chat_id: str,
    ) -> SynchronizationResult:
        lock = self._lock(trusted_owner_id, trusted_chat_id)
        with lock:
            inventory = self._inventory(trusted_owner_id, trusted_chat_id)
            synchronized = inventory.get("synchronized") is True
            expected = int(inventory["source_revision"]) if synchronized else 0
            inventory_branch = inventory.get("branch_generation")
            branch = int(inventory_branch) if synchronized and isinstance(inventory_branch, int) else 1
            provisional = self._project(
                chat_record, trusted_owner_id, trusted_chat_id, expected, branch, "projection-probe",
            )
            active = self._active_projection(provisional)
            key = (trusted_owner_id, trusted_chat_id)
            with self._state_lock:
                previous = self._known.get(key)
            if (
                previous is not None
                and synchronized
                and previous.projection_hash == provisional.projection_hash
                and previous.snapshot_hash == inventory.get("snapshot_hash")
                and previous.branch_generation == branch
            ):
                return SynchronizationResult(
                    disposition="CURRENT",
                    source_revision=expected,
                    branch_generation=branch,
                    projection_hash=previous.projection_hash,
                    message_count=previous.message_count,
                    active_count=previous.active_count,
                )
            if previous is not None:
                branch = max(branch, previous.branch_generation)
                # An unchanged *projection* is not a new branch, whatever the Core's snapshot hash
                # says: our own observe advances that snapshot, so the second announcement of one
                # completion (the outlet and the background-task publisher both announce) never
                # matched on the snapshot and advanced the branch again. That re-revised the round and
                # cleared the lease of the Curator worker holding it, so the run failed
                # `LEASE_CONFLICT`/`INVALID_JOB_TRANSITION` after a full provider call (measured live
                # 2026-09-17: one Continue press moved the branch from 3 to 5).
                if (
                    previous.projection_hash != provisional.projection_hash
                    and not self._is_append(previous.active, active)
                ):
                    branch += 1
            operation_id = self._operation_id(
                trusted_owner_id, trusted_chat_id, expected, branch, active,
            )
            projected = self._project(
                chat_record, trusted_owner_id, trusted_chat_id, expected, branch, operation_id,
            )

            try:
                update = self._post("/v1/memory/source/synchronize", projected.body)
            except (OSError, TimeoutError):
                # The first response may have been lost after publication. An
                # identical retry converges through operation idempotency.
                update = self._post("/v1/memory/source/synchronize", projected.body)
            except ChatMemoryClientError as exc:
                if exc.code != "SOURCE_REVISION_CONFLICT":
                    raise
                refreshed = self._inventory(trusted_owner_id, trusted_chat_id)
                refreshed_revision = int(refreshed["source_revision"])
                refreshed_branch = refreshed.get("branch_generation")
                if refreshed_revision == expected:
                    branch = max(branch + 1, int(refreshed_branch or 1) + 1)
                else:
                    expected = refreshed_revision
                    branch = max(branch, int(refreshed_branch or 1))
                operation_id = self._operation_id(
                    trusted_owner_id, trusted_chat_id, expected, branch, active,
                )
                projected = self._project(
                    chat_record, trusted_owner_id, trusted_chat_id, expected, branch, operation_id,
                )
                update = self._post("/v1/memory/source/synchronize", projected.body)

            if not isinstance(update, dict):
                raise ChatMemoryClientError(503, "INVALID_SYNCHRONIZE_RESPONSE")
            revision = update.get("source_revision")
            disposition = update.get("disposition")
            snapshot_hash = update.get("snapshot_hash")
            if (
                not isinstance(revision, int)
                or isinstance(revision, bool)
                or revision < 1
                or disposition not in {"APPLIED", "DUPLICATE"}
            ):
                raise ChatMemoryClientError(503, "INVALID_SYNCHRONIZE_RESPONSE")
            with self._state_lock:
                self._known[key] = _KnownProjection(
                    active, branch, projected.projection_hash,
                    str(snapshot_hash) if snapshot_hash is not None else None,
                    projected.message_count, projected.active_count,
                )
            return SynchronizationResult(
                disposition=str(disposition),
                source_revision=revision,
                branch_generation=branch,
                projection_hash=projected.projection_hash,
                message_count=projected.message_count,
                active_count=projected.active_count,
            )

    @staticmethod
    def _validate_observation(result: Any) -> dict[str, Any]:
        if not isinstance(result, dict) or not isinstance(result.get("source_update"), dict) or not isinstance(result.get("memory"), dict):
            raise ChatMemoryClientError(503, "INVALID_OBSERVE_RESPONSE")
        update=result["source_update"]
        if update.get("disposition") not in {"APPLIED","DUPLICATE"} or not isinstance(update.get("source_revision"),int):
            raise ChatMemoryClientError(503, "INVALID_OBSERVE_RESPONSE")
        return result

    def _observable_assistant(
        self,
        projected: ProjectedChat,
        assistant_message_id: str,
        user_message_id: str | None,
    ) -> dict[str, Any] | None:
        """Return the projected assistant when it is the active completed source, else None."""
        by_id={str(message["message_id"]):message for message in projected.body["messages"]}
        assistant=by_id.get(assistant_message_id)
        if (
            assistant is None
            or assistant.get("role") != "assistant"
            or assistant.get("completion_state") != "COMPLETE"
            or assistant.get("visible") is not True
            or not projected.body["active_lineage"]
            or projected.body["active_lineage"][-1] != assistant_message_id
            or (user_message_id is not None and assistant.get("parent_message_id") != user_message_id)
        ):
            return None
        return assistant

    def observe(
        self,
        chat_record: Mapping[str, Any],
        *,
        trusted_owner_id: str,
        trusted_chat_id: str,
        assistant_message_id: str,
        user_message_id: str | None = None,
        completion_id: str | None = None,
        receipt_ids: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        """Converge final source and idempotently admit one completed round."""
        if not isinstance(assistant_message_id,str) or not assistant_message_id or len(assistant_message_id)>256:
            raise ChatMemoryProjectionError("assistant message identity is invalid")
        if user_message_id is not None and (not isinstance(user_message_id,str) or not user_message_id or len(user_message_id)>256):
            raise ChatMemoryProjectionError("user message identity is invalid")
        if len(receipt_ids)>64 or any(not isinstance(value,str) or len(value)>256 for value in receipt_ids):
            raise ChatMemoryProjectionError("receipt identities exceed bound")
        key=(trusted_owner_id,trusted_chat_id)
        lock=self._lock(*key)
        with lock:
            # One assistant message can be rewritten in place (Continue Response, an edit, a
            # regeneration). Its identity therefore does not identify what was observed, and
            # replaying a cached admission for a changed body would silently skip the Core
            # admission the rewrite is owed. The local probe is content-only and free of Core
            # calls, so it can key the cache before the source is synchronized.
            probe=self._project(
                chat_record,trusted_owner_id,trusted_chat_id,0,1,"admission-probe",
            )
            probed=self._observable_assistant(probe,assistant_message_id,user_message_id)
            if probed is None:
                raise ChatMemoryProjectionError("finalized assistant is not the active completed source")
            revision=(assistant_message_id,str(probed.get("content_hash") or ""))
            with self._state_lock:
                last=self._last_observations.get(key)
                pending=self._pending_observations.get(key)
            if last is not None and last[0] == revision:
                return dict(last[1])
            if pending is not None and pending[0] == revision:
                # A previous delivery of this exact body may have published and then lost its
                # response. Replaying the stored request unchanged is what makes the retry
                # idempotent, so it must precede any synchronize that could move the source.
                try:
                    result=self._validate_observation(self._post("/v1/memory/observe",pending[1]))
                except ChatMemoryClientError as exc:
                    if exc.status < 500:
                        with self._state_lock: self._pending_observations.pop(key,None)
                    raise
                with self._state_lock:
                    self._pending_observations.pop(key,None)
                    self._last_observations[key]=(pending[0],result)
                return result
            if pending is not None:
                # Nothing holds the per-chat lock but this call, so a retained entry for a
                # different body can only be a stale one from an earlier failure. The body
                # owed now is the newer one; admitting it must not be blocked by the old.
                with self._state_lock: self._pending_observations.pop(key,None)
            synchronized=self.synchronize(
                chat_record,
                trusted_owner_id=trusted_owner_id,
                trusted_chat_id=trusted_chat_id,
            )
            finalized=self._project(
                chat_record,trusted_owner_id,trusted_chat_id,
                synchronized.source_revision,synchronized.branch_generation,"observe-probe",
            )
            assistant=self._observable_assistant(finalized,assistant_message_id,user_message_id)
            if assistant is None:
                raise ChatMemoryProjectionError("finalized assistant is not the active completed source")
            with self._state_lock:
                known=self._known.get(key)
            if known is None:
                raise ChatMemoryClientError(503,"SOURCE_NOT_SYNCHRONIZED")
            active=[identity for identity,_content_hash in known.active]
            operation_value=json.dumps(
                ["observe",trusted_owner_id,trusted_chat_id,assistant_message_id,synchronized.source_revision,known.branch_generation,active],
                separators=(",",":"),ensure_ascii=False,
            ).encode("utf-8")
            body={
                **self._scope(*key),
                "assistant_message_id":assistant_message_id,
                "completion_id":completion_id or assistant_message_id,
                "receipt_ids":list(receipt_ids),
                "source_delta":{
                    "operation_id":"owui-observe-"+hashlib.sha256(operation_value).hexdigest()[:40],
                    "expected_source_revision":synchronized.source_revision,
                    "branch_generation":known.branch_generation,
                    "upserts":[],
                    "delete_message_ids":[],
                    "active_lineage":active,
                },
            }
            if user_message_id is not None: body["user_message_id"]=user_message_id
            with self._state_lock:
                self._pending_observations[key]=(revision,body)
            try:
                result=self._validate_observation(self._post("/v1/memory/observe",body))
            except (OSError,TimeoutError):
                result=self._validate_observation(self._post("/v1/memory/observe",body))
            except ChatMemoryClientError as exc:
                if exc.status < 500:
                    with self._state_lock: self._pending_observations.pop(key,None)
                raise
            with self._state_lock:
                self._pending_observations.pop(key,None)
                self._last_observations[key]=(revision,result)
            return result

    def delete(self, *, trusted_owner_id: str, trusted_chat_id: str) -> dict[str, Any]:
        """Tombstone one trusted instance/owner/chat scope idempotently."""
        key=(trusted_owner_id,trusted_chat_id)
        with self._lock(*key):
            raw=self._post("/v1/memory/source/inventory",self._scope(*key))
            if not isinstance(raw,dict) or not isinstance(raw.get("source_revision"),int):
                raise ChatMemoryClientError(503,"INVALID_INVENTORY_RESPONSE")
            if raw.get("deleted") is True:
                return {"source_update":{"disposition":"CURRENT","source_revision":raw["source_revision"]},"memory":{"state":"LOGICALLY_COMPLETE","hint":"chat.deleted"}}
            expected=int(raw["source_revision"])
            operation_value=json.dumps(["delete",*key,expected],separators=(",",":"),ensure_ascii=False).encode("utf-8")
            body={
                **self._scope(*key),
                "operation_id":"owui-delete-"+hashlib.sha256(operation_value).hexdigest()[:40],
                "expected_source_revision":expected,
            }
            try:
                result=self._post("/v1/memory/source/delete",body)
            except (OSError,TimeoutError):
                result=self._post("/v1/memory/source/delete",body)
            if not isinstance(result,dict) or not isinstance(result.get("source_update"),dict) or not isinstance(result.get("memory"),dict):
                raise ChatMemoryClientError(503,"INVALID_DELETE_RESPONSE")
            if result["source_update"].get("disposition") not in {"APPLIED","DUPLICATE"}:
                raise ChatMemoryClientError(503,"INVALID_DELETE_RESPONSE")
            with self._state_lock:
                self._known.pop(key,None)
                self._pending_observations.pop(key,None)
                self._last_observations.pop(key,None)
            return result
