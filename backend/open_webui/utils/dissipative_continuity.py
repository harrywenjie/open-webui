"""Trusted WebUI source and client for the opt-in schema 34 service."""

import asyncio
import hashlib
import json
from dataclasses import dataclass

from open_webui.utils.dissipative_source import ChatMemoryClientError, ChatMemoryProjectionError, OpenWebUIChatProjector

TRANSPORT = "dissipative.continuity.transport.v1"
PROTOCOL = "dissipative.continuity.v2"
OBSERVATION = "dissipative.observation.events.v1"
CURATION = "dissipative.round-curation.v1"
SELECTION = "dissipative.profile-selection.v1"
PUBLICATION = "dissipative.profile-publication.v1"
FORMAT = "dissipative.source-format-transition.v1"
DELETION = "dissipative.continuity.deletion.v1"
REQUIREMENTS = (
    ("capabilities", {"observation_version": OBSERVATION, "deletion_version": DELETION},
     ["stable-source-v1", "ordered-observation-v1", "profile-guidance-v2", "continuity-deletion-v1"]),
    ("round-curation/capabilities", {"curation_version": CURATION},
     ["split-archive-v1", "explicit-curation-v1", "exact-coverage-v1"]),
    ("profile-selection/capabilities", {"selection_version": SELECTION},
     ["structured-profile-none", "selection-cas-v1", "selection-receipt-v1"]),
    ("profile-publication/capabilities", {"publication_version": PUBLICATION}, ["field-publication-v1", "publication-poll-v1"]),
    ("source-format-transition/capabilities", {"format_transition_version": FORMAT},
     ["drained-format-equivalence-v1", "format-transition-status-v1"]),
)


def digest(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return "sha256:" + hashlib.sha256(encoded.encode()).hexdigest()


def project(chat, scope, grants):
    """Reserve a monotone revision on the locked WebUI row. The journal contains no message text."""
    record = {"id": chat.id, "user_id": chat.user_id, "chat": chat.chat, "current_message_id": chat.current_message_id}
    projection = OpenWebUIChatProjector().complete_sync(
        record, trusted_owner_id=scope["owner_id"], trusted_chat_id=scope["chat_id"],
        instance_id=scope["instance_id"], operation_id="continuity", expected_source_revision=0, branch_generation=1,
    )
    prior = chat.dissipative_source_state or {}
    if prior and prior["instance"] != scope["instance_id"]:
        raise ChatMemoryProjectionError("continuity instance identity changed")
    raw = chat.chat["history"]["messages"]
    active = projection.body["active_lineage"]
    old_active = prior.get("active", [])
    versions = dict(prior.get("versions", {}))
    messages = []
    mode = (chat.variables or {}).get("memory_access_mode", "NORMAL")
    if mode == "OFF":
        active = []
    complete = []
    edited = False
    old_complete = set(prior.get("complete", ()))
    for row in projection.body["messages"]:
        mid = row["message_id"]
        if not row["visible"] or mode == "OFF":
            continue
        role = row["role"]
        author = raw[mid].get("user_id")
        explicit = role == "user" and author == chat.user_id
        producer = "webui-" + digest([role, author if role == "user" else raw[mid].get("model")])[7:]
        eligible = row["evidence_eligible"]
        if role == "user" and row["completion_state"] != "FAILED":
            # FAST needs the persisted current request before the assistant completes.
            eligible = bool(row["content"].strip())
            row["completion_state"] = "COMPLETE"
        if role == "assistant" and eligible:
            complete.append(mid)
        attestation = digest([row["content_hash"], role, producer, explicit, row["parent_message_id"]])
        old_version, old_hash = versions.get(mid, (0, None))
        if old_hash != attestation:
            edited |= mid in old_complete or (old_version > 0 and role == "user")
        versions[mid] = [old_version + int(old_hash != attestation), attestation]
        messages.append({**row, "observed_at": row.get("observed_at"), "memory_mode": mode,
                         "evidence_eligible": eligible, "producer_id": producer,
                         "evidence_class": "USER_EXPLICIT" if explicit else "ORDINARY"})

    acl = digest([chat.share_id, grants, mode == "OFF"])
    branch = prior.get("branch", 1) + int(old_active != active[:len(old_active)] or edited)
    auth = prior.get("auth", 1) + int(bool(prior) and prior["acl"] != acl)
    fingerprint = digest([projection.projection_hash, versions, acl, mode, complete])
    rev = prior.get("revision", 0) + int(fingerprint != prior.get("fingerprint"))
    events = list(prior.get("events", ()))
    deleted = {e["stableSourceId"] for e in events}
    if deleted.intersection(active):
        raise ChatMemoryProjectionError("deleted message identity reused")
    for mid in sorted(set(versions) - raw.keys() - deleted):
        events.append({"eventId": digest(["delete", mid]), "stableSourceId": mid,
                       "sourceRevision": rev, "authorizationRevision": auth, "reason": "SOURCE_DELETED"})
    state = dict(instance=scope["instance_id"], active=active, complete=complete, versions=versions, events=events,
                 fingerprint=fingerprint, revision=rev, branch=branch, auth=auth, acl=acl)
    if state != prior:
        chat.dissipative_source_state = state
    fences = dict(subjectId=chat.user_id, sourceEpoch=1, branchId=f"webui-{branch}",
                  lineageRevision=branch, authorizationRevision=auth)
    sources = []
    for row in messages:
        mid, h = row["message_id"], row["content_hash"]
        version = versions[mid][0]
        binding = dict(scope=scope, **fences, stableSourceId=mid, sourceVersion=version, contentHash=h,
                       projectionId=mid, projectionVersion=version, projectionHash=h)
        sources.append(dict(binding=binding, content=row["content"], projectionText=row["content"]))
    snapshot = dict(scope=scope, **fences, sourceRevision=rev, completeness="COMPLETE", coverage=active,
                    lifecycleReason="SYNCHRONIZED", sources=sources, events=events)
    return snapshot, {"messages": messages, "active_lineage": active}


@dataclass
class ContinuityChat:
    post: object
    scope: dict
    snapshot: dict
    host: dict
    ids: dict

    def call(self, route, **body):
        return self.post("/v1/continuity/" + route, {**body, **self.scope})

    def negotiate(self):
        capabilities = {}
        for path, versions, required in REQUIREMENTS:
            answer = self.call(path, **versions, capabilities=required)
            if answer.get("state") != "SUPPORTED" or not set(required) <= set(answer.get("capabilities", [])):
                raise ChatMemoryClientError(409, "CONTINUITY_CAPABILITY_MISSING")
            capabilities[path.split("/")[0]] = answer
        if capabilities["source-format-transition"].get("schema") != 34:
            raise ChatMemoryClientError(409, "CONTINUITY_SCHEMA_MISMATCH")
        return capabilities

    def synchronize(self):
        result = self.call("source/synchronize-events", observation_version=OBSERVATION,
                           snapshot=self.snapshot, hostMetadata=self.host)
        ids = result.get("messageIds")
        if (result.get("sourceRevision") != self.snapshot["sourceRevision"] or not isinstance(ids, dict)
                or ids.keys() != set(self.snapshot["coverage"]) or len(set(ids.values())) != len(ids)
                or not all(isinstance(i, str) and i.startswith("continuity-") for i in ids.values())):
            raise ChatMemoryClientError(503, "INVALID_CONTINUITY_SOURCE_RESPONSE")
        self.ids = ids
        return self

    def translated(self, body):
        result = dict(body)
        for key in ("user_message_id", "assistant_message_id", "current_message_id"):
            if result.get(key):
                if result[key] not in self.ids:
                    raise ChatMemoryClientError(409, "MESSAGE_OUTSIDE_ACTIVE_BRANCH")
                result[key] = self.ids[result[key]]
        return result

    def refs(self, completion=None, *, recover=False):
        rows = [r for r in self.host["messages"] if r["evidence_eligible"] and r["completion_state"] == "COMPLETE"]
        ends = [i for i, r in enumerate(rows) if r["role"] == "assistant"]
        if completion is not None:
            if not recover and self.host["active_lineage"][-1:] != [completion]:
                return []
            selected = next((i for i, end in enumerate(ends) if rows[end]["message_id"] == completion), None)
            if selected is None:
                return []
            ends = ends[:selected+1]
            rows = rows[(ends[-2]+1 if len(ends) > 1 else 0):ends[-1]+1]
        else:
            rows = rows[:ends[-1]+1] if ends else []
        bindings = {s["binding"]["projectionId"]: s["binding"] for s in self.snapshot["sources"]}
        return [dict(messageId=self.ids[r["message_id"]], stableSourceId=r["message_id"],
                     sourceVersion=bindings[r["message_id"]]["sourceVersion"], contentHash=r["content_hash"]) for r in rows]

    def status(self, request=None):
        return self.call("round-curation/status", curation_version=CURATION, **({"requestId": request} if request else {}))

    def coverage(self):
        refs = self.refs()
        covered = {r["messageId"] for r in self.status()["covered"]}
        current = sum(r["messageId"] in covered for r in refs)
        archive = "no completed turn"
        if refs:
            # Match the exact receipt for the last completed assistant even during the next send.
            end = len(refs) - 1
            roles = {row["message_id"]: row["role"] for row in self.host["messages"]}
            start = max((i for i in range(end) if roles[refs[i]["stableSourceId"]] == "assistant"), default=-1) + 1
            try:
                archive = self.status("archive-" + digest(refs[start:])[7:])["state"]
            except ChatMemoryClientError as exc:
                if exc.code != "CURATION_REQUEST_NOT_FOUND":
                    raise
                archive = "pending"
        return {"curated": current, "eligible": len(refs), "latestArchive": archive,
                "summary": f"Latest turn archive: {archive}. Curator: {current} of {len(refs)} current sources processed."}

    def admit(self, kind, request_id, completion=None, *, recover=False):
        refs = self.refs(completion, recover=recover)
        if kind == "ARCHIVE":
            if not refs:
                return {"disposition": "NOT_ELIGIBLE"}
            request_id = "archive-" + digest(refs)[7:]
        try:
            existing = self.status(request_id)
        except ChatMemoryClientError as exc:
            if exc.status != 404 or exc.code != "CURATION_REQUEST_NOT_FOUND":
                raise
        else:
            receipt = existing["receipt"]
            if receipt["kind"] != kind:
                raise ChatMemoryClientError(409, "REQUEST_KIND_CONFLICT")
            return {**receipt, "replayed": True, "currentState": existing["state"]}
        status = self.status()
        if kind == "CURATION":
            reserved = {r["messageId"] for r in status["reserved"]}
            # Core admits contiguous ranges of at most 1,024 sources per user request.
            pending = []
            for ref in refs:
                if ref["messageId"] in reserved:
                    if pending:
                        break
                    continue
                pending.append(ref)
                if len(pending) == 1024:
                    break
            refs = pending
        authority = self.call("manage", action="STATUS")
        payload = {k: self.snapshot[k] for k in ("subjectId", "sourceEpoch", "sourceRevision", "branchId",
                                                  "lineageRevision", "authorizationRevision")}
        payload.update(scopeGeneration=authority["scope_generation"], profile=status["profile"], sources=refs,
                       baselineDigest=status["baselineDigest"], predecessorJobId=status["predecessorJobId"],
                       boundaryId=completion or request_id, reason="completed-turn" if completion else "user-request")
        signature = digest(dict(version=CURATION, kind=kind, scope=self.scope, payload=payload))
        route = "round-curation/archive" if kind == "ARCHIVE" else "round-curation/admit"
        return self.call(route, curation_version=CURATION, requestId=request_id, payload=payload, payloadDigest=signature)

    def restore_archives(self):
        for row in self.host["messages"]:
            if row["role"] == "assistant" and row["evidence_eligible"] and row["memory_mode"] == "NORMAL":
                self.admit("ARCHIVE", None, row["message_id"], recover=True)

    def select(self, data):
        payload = dict(subjectId=self.snapshot["subjectId"], scopeGeneration=self.call("manage", action="STATUS")["scope_generation"],
                       expectedSelectionRevision=data["expectedSelectionRevision"], mode=data["mode"],
                       profile_id=data.get("profile_id"), profile_revision=data.get("profile_revision"))
        return self.call("profile-selection/set", selection_version=SELECTION, payload=payload, requestId=data["requestId"],
                         payloadDigest=digest(dict(version=SELECTION, scope=self.scope, payload=payload)))


async def synchronized(post, scope):
    from sqlalchemy import select
    from open_webui.models.access_grants import AccessGrant
    from open_webui.models.chats import Chats
    from open_webui.models.shared_chats import SharedChat

    # Commit the host revision before transport. A delayed packet can only replay exactly or lose Core's CAS.
    async with Chats._chat_transaction(scope["chat_id"]) as (db, row):
        if row is None or row.user_id != scope["owner_id"]:
            raise ChatMemoryClientError(404, "CHAT_NOT_FOUND")
        grants = (await db.execute(select(AccessGrant.principal_type, AccessGrant.principal_id, AccessGrant.permission)
                  .filter_by(resource_type="shared_chat", resource_id=row.id)
                  .order_by(AccessGrant.principal_type, AccessGrant.principal_id, AccessGrant.permission))).all()
        share_mode = await db.scalar(select(SharedChat.chat["share_mode"].as_string()).filter_by(id=row.share_id)) if row.share_id else None
        snapshot, host = project(row, scope, [share_mode, [list(g) for g in grants]])
    return await asyncio.to_thread(ContinuityChat(post, scope, snapshot, host, {}).synchronize)


def delete(post, scope):
    effect = "PERMANENT_SCOPE_DELETE"
    return post("/v1/continuity/deletion/apply", {**scope, "confirm": effect, "deletion_version": DELETION,
                "operationHash": digest(dict(version=DELETION, scope=scope, effect=effect))})


def handle_action(client, action, data):
    allowed = {
        "CURATION_ADMIT": {"requestId"}, "CURATION_STATUS": {"requestId"}, "SELECTION_GET": {"requestId"},
        "SELECTION_SET": {"requestId", "expectedSelectionRevision", "mode", "profile_id", "profile_revision"},
        "PUBLICATION_GET": {"jobId"}, "FORMAT_INSPECT": set(), "PROFILE_STATE": set(),
    }
    if action == "PROFILE_SELECT":
        raise ChatMemoryClientError(409, "SELECTION_REVISION_REQUIRED")
    if set(data) - allowed[action]:
        raise ChatMemoryClientError(400, "INVALID_CONTINUITY_FIELDS")
    request = data.get("requestId")
    if "requestId" in data or action in {"CURATION_ADMIT", "SELECTION_SET"}:
        if not isinstance(request, str) or not 1 <= len(request) <= 96:
            raise ChatMemoryClientError(400, "INVALID_REQUEST_ID")
    if action == "CURATION_ADMIT":
        return client.admit("CURATION", "curate-" + request)
    if action == "CURATION_STATUS":
        return client.status("curate-" + request if request else None)
    if action == "SELECTION_GET":
        return client.call("profile-selection/get", selection_version=SELECTION, **data)
    if action == "SELECTION_SET":
        if data.get("mode") not in {"NONE", "SELECTED"} or type(data.get("expectedSelectionRevision")) is not int:
            raise ChatMemoryClientError(400, "INVALID_SELECTION")
        return client.select(data)
    if action == "FORMAT_INSPECT":
        return client.call("source-format-transition/inspect", format_transition_version=FORMAT)
    publication = client.call("profile-publication/get", publication_version=PUBLICATION, **data)
    for field in publication["fields"]:
        if field["availability"] != "AVAILABLE":
            field["value"] = None
    if action == "PUBLICATION_GET":
        return publication
    selection = publication["selection"]
    authority = client.call("manage", action="STATUS")
    state = {**selection, "branch_generation": client.snapshot["lineageRevision"],
             "scope_generation": authority["scope_generation"], "nodes": []}
    if selection["mode"] == "SELECTED":
        tree = client.call("manage", action="PROFILE_STATE")
        if any(tree.get(k) != selection[k] for k in ("profile_id", "profile_revision", "profile_hash", "selection_revision")):
            raise ChatMemoryClientError(409, "PROFILE_SELECTION_CHANGED")
        fields = {f["fieldId"]: f for f in publication["fields"]}
        state["nodes"] = tree["nodes"]
        pending = list(state["nodes"])
        while pending:
            node = pending.pop()
            pending.extend(node.get("children", ()))
            if node.get("kind") != "GROUP":
                field = fields.get(node.get("field_id"), {})
                node.update(status=field.get("status", "UNKNOWN"), value=field.get("value"))
    return state
