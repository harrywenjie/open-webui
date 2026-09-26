from __future__ import annotations

import asyncio, json, logging, os, urllib.error, urllib.request
from contextlib import suppress
from dataclasses import asdict
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, status
try:  # the overlay's own test harness stubs `fastapi`; `Request` is a type annotation only
    from fastapi import Request
except ImportError:  # pragma: no cover - exercised by the integration harness
    Request=object
from open_webui.internal.db import get_async_db_context, get_async_session
from open_webui.models.chats import Chat, ChatModel, Chats
from open_webui.utils.auth import get_verified_user
from open_webui.utils.dissipative_source import (
    ChatMemoryClientError,
    ChatMemoryProjectionError,
    OpenWebUISourceSynchronizer,
)
from open_webui.utils.dissipative_observation import ObservationStatusRegistry
from open_webui.utils.dissipative_evaluation_push import (
    ensure_callback_token,
    publish_evaluation_completed,
    token_matches,
)
from open_webui.utils.dissipative_liveness import SourceLivenessSupervisor, error_class
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router=APIRouter()
log=logging.getLogger(__name__)
ALLOWED=frozenset({"STATUS","SET_MODE","SET_AUTONOMOUS_WRITING","TRACKER_PROJECTION","EVALUATION_WAIT","PROFILE_STATE","PROFILE_LIST","PROFILE_GET","PROFILE_PREVIEW","PROFILE_CREATE","PROFILE_REVISE","PROFILE_DUPLICATE","PROFILE_SELECT","PROFILE_ARCHIVE","PROFILE_DELETE","INSPECT_PAGE","WHY_REMEMBERED","ADD","CORRECT","EDIT","FORGET","REDACT","PIN","UNPIN","CURATOR_PREFERENCES_GET","SET_CURATOR_USER_DEFAULTS","SET_CURATOR_CHAT_OVERRIDE","RESET_CURATOR_CHAT_OVERRIDE"})
FORBIDDEN=frozenset({"instance_id","owner_id","actor_id","role","authority","api_key","bridge_secret","source_token","qwen_api_key","client_capability","curator_max_in_flight","curator_queue_age_seconds","curator_execution_timeout_seconds","curator_debug_trace","curator_debug_capture_bytes"})
ENABLED_MODES=frozenset({"NORMAL","READ_ONLY"})
# Bound on the recent-chat window every reconciliation selects from.
RECENT_CHAT_LIMIT=64
# Phase 5H B1/D5: how long a send waits for the previous turn's evaluation, and the extra time the
# HTTP client allows the Core to answer within. The wait is skipped, never retried, on expiry. The
# Core polls with a growing interval, so it can overshoot its own deadline by about a second; the
# grace is what keeps a slow Core from turning into a socket timeout instead of a clean skip.
EVALUATION_WAIT_SECONDS=30.0
_EVALUATION_WAIT_GRACE_SECONDS=10.0

class ManagementRequest(BaseModel):
    chat_id: str=Field(min_length=1,max_length=256)
    action: str=Field(min_length=1,max_length=64)
    payload: dict=Field(default_factory=dict)

class SourceSynchronizationRequest(BaseModel):
    chat_id: str=Field(min_length=1,max_length=256)

class EvaluationCompletedRequest(BaseModel):
    """Phase 5H H1. Identity-only: no source prose and no memory content crosses this route."""
    instance: str=Field(min_length=1,max_length=128)
    owner_id: str=Field(min_length=1,max_length=256)
    chat_id: str=Field(min_length=1,max_length=256)
    round_id: str=Field(min_length=1,max_length=256)
    assistant_message_id: str=Field(min_length=1,max_length=256)
    disposition: str=Field(min_length=1,max_length=64)
    semantic_revision: int=0
    evaluation_revision: int=Field(default=0,ge=0)
    event_version: int=Field(default=1,ge=1,le=2)
    phase: str=Field(default="TERMINAL",pattern="^(QUEUED|RUNNING|TERMINAL)$")
    scope_generation: int=Field(default=0,ge=0)
    branch_generation: int=Field(default=0,ge=0)
    error_class: str | None=Field(default=None,max_length=96)

class EvaluationWaitRequest(BaseModel):
    """Phase 5H B1/B3. The internal send-hold request; the bound is clamped, not trusted."""
    owner_id: str=Field(min_length=1,max_length=256)
    chat_id: str=Field(min_length=1,max_length=256)
    maximum_wait_seconds: float=EVALUATION_WAIT_SECONDS

def _callback_data_root() -> Path:
    """Where the shared callback secret lives.

    `OPEN_WEBUI_DATA_DIR` when the deployment sets it, `~/open-webui/data` otherwise -- which is
    this host's durable data tree and the same place `.webui_secret_key` already lives. The Core's
    `--evaluation-callback-token-file` default resolves to the identical path.
    """
    configured=str(os.environ.get("OPEN_WEBUI_DATA_DIR") or "").strip()
    return Path(configured) if configured else Path.home()/"open-webui"/"data"

def _positive_number_from_payload(value, default: float) -> float:
    """Read one bounded positive numeric value from a request payload, else the default."""
    try: number=float(str(value).strip())
    except (TypeError,ValueError): return default
    if number != number or number in (float("inf"),float("-inf")) or number <= 0: return default
    return min(number,EVALUATION_WAIT_SECONDS)

def _bearer(request: Request) -> str:
    value=str(request.headers.get("authorization") or "")
    if value[:7].lower() != "bearer ": return ""
    return value[7:].strip()

def _callback_expected_token() -> str:
    """The shared callback secret, or "" when it is not provisioned."""
    try:
        return ensure_callback_token(_callback_data_root())
    except OSError:
        return ""

def _internal_evaluation_wait(owner_id: str,chat_id: str,maximum_wait_seconds: float) -> dict:
    """Ask the adapter's own internal route for the bounded send hold.

    Deliberately *not* a direct Core call from `prepare_for_chat`: the wait is the one place a
    long hold could be requested, so it goes through the same secret-guarded internal surface the
    Core's completion push uses, where the bound is clamped server-side and the credential never
    leaves the two services. Returns the verdict, or `{}` when the wait could not be obtained at
    all — in which case the caller proceeds (owner decision D5: skip, never retry).
    """
    token=_callback_expected_token()
    if not token:
        return {}
    url=f"http://127.0.0.1:{os.environ.get('CHAT_MEMORY_OPEN_WEBUI_PORT','8080')}/api/v1/chat-memory/internal/evaluation-wait"
    body=json.dumps({"owner_id":owner_id,"chat_id":chat_id,
                     "maximum_wait_seconds":float(maximum_wait_seconds)},
                    separators=(",",":"),ensure_ascii=False).encode("utf-8")
    request=urllib.request.Request(url,data=body,method="POST",headers={
        "Authorization":"Bearer "+token,"Content-Type":"application/json",
    })
    with urllib.request.urlopen(request,timeout=float(maximum_wait_seconds)+_EVALUATION_WAIT_GRACE_SECONDS) as response:
        raw=response.read(65537)
    if len(raw)>65536: raise RuntimeError("evaluation wait response exceeds bound")
    value=json.loads(raw.decode("utf-8"))
    if not isinstance(value,dict): raise RuntimeError("invalid evaluation wait response")
    return value

def _client(path: str, body: dict, timeout: float=3) -> dict:
    key_path=Path(os.environ["CHAT_MEMORY_API_KEY_FILE"])
    api_key=key_path.read_text(encoding="utf-8").strip()
    instance_id=os.environ["CHAT_MEMORY_INSTANCE_ID"].strip()
    base=os.environ.get("CHAT_MEMORY_LOOPBACK_URL","http://127.0.0.1:18111").rstrip("/")
    if not base.startswith(("http://127.0.0.1:","http://localhost:")) or not api_key or not instance_id or len(instance_id)>128: raise RuntimeError("gateway configuration unavailable")
    request_body={**body,"api_version":"chat-memory.client.v1","instance_id":instance_id,"client_capability":"chat-memory-curator-redesign-phase4"}
    req=urllib.request.Request(base+path,data=json.dumps(request_body,separators=(",",":"),ensure_ascii=False).encode(),method="POST",headers={"Authorization":"Bearer "+api_key,"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(req,timeout=timeout) as response: raw=response.read(1024*1024+1)
    except urllib.error.HTTPError as exc:
        raw=exc.read(65537)
        try: error=json.loads(raw).get("error") if len(raw)<=65536 else None
        except (json.JSONDecodeError,UnicodeDecodeError): error=None
        raise ChatMemoryClientError(exc.code,str(error or "CHAT_MEMORY_HTTP_ERROR")) from exc
    if len(raw)>1024*1024: raise RuntimeError("bounded response exceeded")
    value=json.loads(raw)
    if not isinstance(value,dict) or value.get("api_version")!="chat-memory.client.v1" or value.get("ok") is not True or not isinstance(value.get("result"),dict): raise RuntimeError("invalid response")
    return value["result"]

_source_synchronizer: OpenWebUISourceSynchronizer | None=None
_source_synchronizer_instance: str | None=None
_startup_reconciliation_task: asyncio.Task | None=None
_startup_reconciliation_status={"state":"NOT_STARTED","attempts":0,"error_class":None,"selected":0,"synchronized":0,"failed":0}
_liveness_supervisor: SourceLivenessSupervisor | None=None
_observation_status=ObservationStatusRegistry(maximum=256)

def _synchronizer() -> OpenWebUISourceSynchronizer:
    global _source_synchronizer,_source_synchronizer_instance
    instance_id=os.environ["CHAT_MEMORY_INSTANCE_ID"].strip()
    if _source_synchronizer is None or _source_synchronizer_instance != instance_id:
        _source_synchronizer=OpenWebUISourceSynchronizer(instance_id,_client)
        _source_synchronizer_instance=instance_id
    return _source_synchronizer

async def _synchronize_chat(chat,owner_id: str,chat_id: str) -> dict:
    record={"id":chat.id,"user_id":chat.user_id,"chat":chat.chat}
    try:
        result=await asyncio.to_thread(
            _synchronizer().synchronize,record,
            trusted_owner_id=owner_id,trusted_chat_id=chat_id,
        )
    except ChatMemoryProjectionError:
        raise HTTPException(status_code=409,detail="Open WebUI chat source is not projectable") from None
    except (ChatMemoryClientError,OSError,TimeoutError,KeyError,ValueError,RuntimeError,urllib.error.URLError,json.JSONDecodeError):
        raise HTTPException(status_code=503,detail="Dissipative Memory source synchronization did not complete") from None
    return asdict(result)

async def _owned_chat(owner_id: str,chat_id: str):
    chat=await Chats.get_chat_by_id_and_user_id(chat_id,owner_id)
    if not chat: raise ChatMemoryProjectionError("trusted Open WebUI chat ownership is unavailable")
    return chat

async def prepare_for_chat(owner_id: str,chat_id: str,request_text: str,correlation_id: str,user_message_id: str | None=None,assistant_message_id: str | None=None) -> dict:
    """Prepare memory for a trusted Open WebUI turn without exposing credentials.

    Phase 5H B1/B3: this runs before the Core `prepare` and before the model call, so it is where the
    **send hold** lives (owner decision D3/D4) — typing is never blocked, and the enforcement is here
    rather than in the browser so it holds for every client. The Core waits, bounded, for the previous
    turn's evaluation to reach a terminal state; if the bound expires the turn proceeds and the Core
    records the skipped evaluation as a coverage gap (`EVALUATION_WAIT_TIMEOUT`), with no retry (D5).
    A failure to obtain the wait verdict is *not* a reason to hold the send: the memory system is an
    enhancement, so an unavailable Core means the turn goes ahead exactly as it does today.
    """
    if not isinstance(request_text,str) or len(request_text)>8000: raise ChatMemoryProjectionError("request text exceeds bound")
    chat=await _owned_chat(owner_id,chat_id)
    await _synchronize_chat(chat,owner_id,chat_id)
    body={"owner_id":owner_id,"chat_id":chat_id,"request_text":request_text,"correlation_id":correlation_id,"tracker_token_budget":256}
    if user_message_id: body["user_message_id"]=user_message_id
    if assistant_message_id: body["assistant_message_id"]=assistant_message_id
    try:
        await asyncio.to_thread(_internal_evaluation_wait,owner_id,chat_id,EVALUATION_WAIT_SECONDS)
    except Exception:
        # D5's "skip, never retry" applies to the wait as much as to the evaluation: a Core that
        # cannot answer the wait question must not become a reason to refuse the user's turn.
        log.warning("Dissipative Memory evaluation wait was not obtained; continuing without it")
    result=await asyncio.to_thread(_client,"/v1/memory/prepare",body)
    memory=result.get("memory")
    if not isinstance(memory,dict): raise ChatMemoryClientError(503,"INVALID_PREPARE_RESPONSE")
    return memory

async def recall_for_chat(owner_id: str,chat_id: str,request: dict) -> dict:
    """Recall through server-derived Open WebUI ownership and instance scope."""
    chat=await _owned_chat(owner_id,chat_id)
    await _synchronize_chat(chat,owner_id,chat_id)
    body={**request,"owner_id":owner_id,"chat_id":chat_id}
    return await asyncio.to_thread(_client,"/v1/memory/recall",body,8)

async def observe_finalized(owner_id: str,chat_id: str,assistant_message_id: str,receipt_ids: tuple[str,...]=()) -> dict:
    """Admit only the active persisted assistant from the authoritative chat."""
    try:
        chat=await _owned_chat(owner_id,chat_id)
        messages=((chat.chat or {}).get("history") or {}).get("messages") or {}
        assistant=messages.get(assistant_message_id) if isinstance(messages,dict) else None
        user_message_id=assistant.get("parentId") if isinstance(assistant,dict) else None
        record={"id":chat.id,"user_id":chat.user_id,"chat":chat.chat}
        result=await asyncio.to_thread(
            _synchronizer().observe,record,
            trusted_owner_id=owner_id,trusted_chat_id=chat_id,
            assistant_message_id=assistant_message_id,user_message_id=user_message_id,
            completion_id=assistant_message_id,receipt_ids=receipt_ids,
        )
    except Exception as exc:
        _observation_status.failed(owner_id,chat_id,getattr(exc,"code","INTERNAL_ERROR"))
        raise
    memory=result.get("memory") if isinstance(result,dict) else None
    disposition=memory.get("disposition") if isinstance(memory,dict) else None
    _observation_status.succeeded(owner_id,chat_id,disposition)
    return result

async def reconcile_hint(owner_id: str,chat_id: str) -> dict:
    """Treat edit/regeneration events as hints; the stored chat remains authoritative."""
    chat=await _owned_chat(owner_id,chat_id)
    return await _synchronize_chat(chat,owner_id,chat_id)

async def delete_chat_memory(owner_id: str,chat_id: str) -> dict:
    """Tombstone a deleted chat after Open WebUI has removed its source row."""
    return await asyncio.to_thread(
        _synchronizer().delete,
        trusted_owner_id=owner_id,trusted_chat_id=chat_id,
    )

async def delete_all_chat_memory(owner_id: str,db: AsyncSession) -> int:
    """Tombstone every owner chat in bounded pages before Open WebUI deletes rows."""
    cursor=""
    deleted=0
    while True:
        result=await db.execute(
            select(Chat.id)
            .where(Chat.user_id == owner_id,Chat.id > cursor)
            .order_by(Chat.id)
            .limit(64)
        )
        identities=[str(value) for value in result.scalars().all()]
        for chat_id in identities:
            await delete_chat_memory(owner_id,chat_id)
            deleted+=1
        if len(identities)<64: return deleted
        cursor=identities[-1]

async def _eligible_recent_chats() -> list:
    """Select the bounded recent eligible Open WebUI chats, newest first.

    A chat whose access mode is `OFF` is excluded here, not only at push time. The
    liveness loop probes every chat this returns and escalates to the bounded
    reconciliation when one of them is unavailable, while `_reconcile_recent_chats`
    deliberately never pushes an `OFF` chat. An `OFF` scope inside the probed window
    could therefore never be repaired: every cycle would report `NO_PROGRESS`, the
    no-progress count would grow without bound, and the loop would keep running the
    expensive reconciliation at the capped backoff forever. The bound still applies
    to the recent window, so an `OFF` chat inside it simply leaves fewer scopes to
    reconcile.
    """
    async with get_async_db_context() as db:
        result=await db.execute(
            select(Chat)
            .where(Chat.meta["internal"].as_boolean().is_not(True))
            .order_by(Chat.updated_at.desc(),Chat.id)
            .limit(RECENT_CHAT_LIMIT)
        )
        chats=[ChatModel.model_validate(value) for value in result.scalars().all()]
    return [chat for chat in chats if _memory_access_mode(chat) != "OFF"]

def _memory_access_mode(chat) -> str:
    return str((chat.variables or {}).get("memory_access_mode") or "NORMAL")

def _positive_number(name: str,default: float) -> float:
    """Read one bounded positive numeric CHAT_MEMORY_* setting, else the default."""
    try: value=float(str(os.environ.get(name,default)).strip())
    except (TypeError,ValueError): return default
    if value != value or value in (float("inf"),float("-inf")) or value <= 0: return default
    return value

def _positive_integer(name: str,default: int) -> int:
    try: value=int(str(os.environ.get(name,default)).strip())
    except (TypeError,ValueError): return default
    return value if value >= 1 else default

def _switch(name: str,default: str="1") -> bool:
    return os.environ.get(name,default) != "0"

async def _source_scope_available(chat) -> bool:
    """Cheap content-free inventory probe for one eligible scope.

    A scope whose authoritative source is not current is the only condition that
    escalates the loop from polling to the bounded reconciliation. A scope the
    service reports as tombstoned is deliberately excluded from recovery.
    """
    inventory=await asyncio.to_thread(_client,"/v1/memory/source/inventory",{"owner_id":chat.user_id,"chat_id":chat.id})
    return inventory.get("deleted") is not True and inventory.get("synchronized") is True

async def _reconcile_recent_chats() -> dict:
    global _startup_reconciliation_status
    status_value={"state":"RUNNING","attempts":0,"error_class":None,"selected":0,"synchronized":0,"failed":0}
    _startup_reconciliation_status=status_value
    try:
        chats=await _eligible_recent_chats()
        status_value["selected"]=len(chats)
        for chat in chats:
            if _memory_access_mode(chat) == "OFF":
                continue
            try:
                await _synchronize_chat(chat,chat.user_id,chat.id)
                status_value["synchronized"]+=1
            except HTTPException:
                status_value["failed"]+=1
            await asyncio.sleep(0)
        status_value["state"]="COMPLETE" if status_value["failed"] == 0 else "DEGRADED"
    except asyncio.CancelledError:
        status_value["state"]="CANCELLED"
        raise
    except Exception as exc:
        status_value["state"]="FAILED"
        status_value["failed"]+=1
        status_value["error_class"]=error_class(exc)
        log.warning("Dissipative Memory startup reconciliation failed: %s",status_value["error_class"])
    return status_value

def _liveness_supervisor_for() -> SourceLivenessSupervisor:
    """Return the process-wide supervisor, creating it on first use."""
    global _liveness_supervisor
    if _liveness_supervisor is None:
        _liveness_supervisor=SourceLivenessSupervisor(
            chat_records=_eligible_recent_chats,
            chat_identity=lambda chat:(chat.user_id,chat.id),
            available=_source_scope_available,
            repair=_reconcile_recent_chats,
            enabled=_switch("CHAT_MEMORY_LIVENESS_SYNC"),
            interval_seconds=_positive_number("CHAT_MEMORY_LIVENESS_INTERVAL_SECONDS",300.0),
            maximum_backoff_seconds=_positive_number("CHAT_MEMORY_LIVENESS_MAX_BACKOFF_SECONDS",3600.0),
            maximum_consecutive_failures=_positive_integer("CHAT_MEMORY_LIVENESS_MAX_FAILURES",5),
            probe_limit=_positive_integer("CHAT_MEMORY_LIVENESS_PROBE_LIMIT",8),
        )
    return _liveness_supervisor

def _source_liveness_status() -> dict:
    """Expose loop state, attempt counts and the last error class only."""
    supervisor=_liveness_supervisor
    return {
        "startup":dict(_startup_reconciliation_status),
        "loop":supervisor.status() if supervisor is not None else None,
    }

async def _startup_reconcile_with_retry() -> dict:
    """Retry a failed startup reconciliation a bounded number of times."""
    global _startup_reconciliation_status
    attempts=_positive_integer("CHAT_MEMORY_STARTUP_SYNC_ATTEMPTS",3)
    backoff=2.0
    status_value={"state":"NOT_STARTED","attempts":0,"error_class":None,"selected":0,"synchronized":0,"failed":0}
    for attempt in range(1,attempts+1):
        result=await _reconcile_recent_chats()
        status_value={**result,"attempts":attempt}
        _startup_reconciliation_status=status_value
        if result.get("state") in {"COMPLETE","CANCELLED"}:
            return status_value
        if attempt < attempts:
            await asyncio.sleep(backoff)
            backoff=min(backoff*2,_positive_number("CHAT_MEMORY_STARTUP_SYNC_MAX_BACKOFF_SECONDS",60.0))
    log.warning(
        "Dissipative Memory startup reconciliation exhausted %s attempt(s): state=%s error_class=%s",
        attempts,status_value["state"],status_value.get("error_class") or "PER_CHAT_SYNCHRONIZATION_FAILURE",
    )
    return status_value

@router.on_event("startup")
async def start_source_reconciliation() -> None:
    global _startup_reconciliation_task
    if _switch("CHAT_MEMORY_STARTUP_SYNC"):
        _startup_reconciliation_task=asyncio.create_task(
            _startup_reconcile_with_retry(),name="chat-memory-source-reconciliation",
        )
    supervisor=_liveness_supervisor_for()
    if supervisor.enabled:
        supervisor.start()

@router.on_event("shutdown")
async def stop_source_reconciliation() -> None:
    global _startup_reconciliation_task
    if _startup_reconciliation_task is not None and not _startup_reconciliation_task.done():
        _startup_reconciliation_task.cancel()
        with suppress(asyncio.CancelledError): await _startup_reconciliation_task
    _startup_reconciliation_task=None
    if _liveness_supervisor is not None:
        await _liveness_supervisor.stop()

def _mode_variables(current: dict | None, mode: str) -> dict:
    values=dict(current or {})
    previous=str(values.get("memory_previous_enabled_mode") or "NORMAL")
    if previous not in ENABLED_MODES: previous="NORMAL"
    values["memory_access_mode"]=mode
    if mode in ENABLED_MODES: values["memory_previous_enabled_mode"]=mode
    else: values["memory_previous_enabled_mode"]=previous
    return values

async def ensure_initial_mode(owner_id: str, chat_id: str, variables: dict) -> None:
    """Persist a new chat's non-default draft mode before filters/events can run."""
    mode=str((variables or {}).get("memory_access_mode") or "NORMAL")
    if mode == "NORMAL": return
    if mode not in {"READ_ONLY","OFF"}: raise HTTPException(status_code=400,detail="Invalid memory access mode")
    try: result=await asyncio.to_thread(_client,"/v1/memory/manage",{"action":"SET_MODE","owner_id":owner_id,"chat_id":chat_id,"mode":mode,"base_revision":0})
    except (OSError,KeyError,ValueError,RuntimeError,urllib.error.URLError,json.JSONDecodeError):
        raise HTTPException(status_code=503,detail="Dissipative Memory mode update did not complete") from None
    if result.get("state") not in {"MODE_UPDATED","DISABLED"} or result.get("mode") not in {mode,"OFF"}:
        raise HTTPException(status_code=503,detail="Dissipative Memory mode update was not accepted")

@router.post("/manage")
async def manage(form: ManagementRequest,user=Depends(get_verified_user),db: AsyncSession=Depends(get_async_session)):
    action=form.action.upper()
    # Ownership is the *authenticated session's*, never the payload's: an owner id in the payload is
    # rejected outright (`FORBIDDEN`), and `user.id` is what reaches the Core. That is also why the
    # router never reads a request field for it.
    if action not in ALLOWED or set(form.payload)&FORBIDDEN: raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,detail="Invalid memory management request")
    if action == "SET_AUTONOMOUS_WRITING" and type(form.payload.get("enabled")) is not bool:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,detail="Invalid autonomous writing preference")
    chat=await Chats.get_chat_by_id_and_user_id(form.chat_id,user.id,db=db)
    if not chat: raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,detail="Chat not found")
    body={**form.payload,"action":action,"owner_id":user.id,"chat_id":form.chat_id}
    scope={"owner_id":user.id,"chat_id":form.chat_id}
    current_variables=dict(chat.variables or {})
    try:
        if action == "PROFILE_STATE": await _synchronize_chat(chat,user.id,form.chat_id)
        if action == "EVALUATION_WAIT":
            # B1/B3. The wait must not be granted forever just because a browser asked for it.
            requested=_positive_number_from_payload(form.payload.get("maximum_wait_seconds"),EVALUATION_WAIT_SECONDS)
            body={**scope,"action":"EVALUATION_WAIT","maximum_wait_seconds":requested}
            return await asyncio.to_thread(_client,"/v1/memory/manage",body,requested+_EVALUATION_WAIT_GRACE_SECONDS)
        if action == "SET_MODE":
            target=str(form.payload.get("mode") or "")
            if target not in {"NORMAL","READ_ONLY","OFF"}: raise HTTPException(status_code=400,detail="Invalid memory access mode")
            previous=await asyncio.to_thread(_client,"/v1/memory/manage",{"action":"STATUS","owner_id":user.id,"chat_id":form.chat_id})
            result=await asyncio.to_thread(_client,"/v1/memory/manage",body)
            if result.get("state") == "DISABLED": return {**result,"client_previous_enabled_mode":"NORMAL"}
            updated=await Chats.update_chat_variables_by_id(form.chat_id,_mode_variables(current_variables,target),db=db,touch=False)
            if updated is None:
                try:
                    await asyncio.to_thread(_client,"/v1/memory/manage",{"action":"SET_MODE","owner_id":user.id,"chat_id":form.chat_id,"mode":previous.get("mode","NORMAL"),"base_revision":result.get("config_revision")})
                finally:
                    raise HTTPException(status_code=503,detail="Dissipative Memory mode persistence did not complete")
            return {**result,"client_previous_enabled_mode":_mode_variables(current_variables,target)["memory_previous_enabled_mode"]}

        result=await asyncio.to_thread(_client,"/v1/memory/manage",body)
        if action == "STATUS" and result.get("state") == "READY":
            if result.get("integration",{}).get("adapter") != "chat-memory-curator-redesign-phase4":
                return {"state":"INCOMPATIBLE","reason":"Dissipative Memory Core and Adapter versions do not match."}
            observation=_observation_status.get(user.id,form.chat_id)
            synchronized=_mode_variables(current_variables,str(result["mode"]))
            if synchronized != current_variables:
                updated=await Chats.update_chat_variables_by_id(form.chat_id,synchronized,db=db,touch=False)
                if updated is None: raise HTTPException(status_code=503,detail="Dissipative Memory mode persistence did not complete")
            result={**result,"observation":observation,"client_previous_enabled_mode":synchronized["memory_previous_enabled_mode"],"source_liveness":_source_liveness_status()}
        return result
    except (OSError,KeyError,ValueError,RuntimeError,urllib.error.URLError,json.JSONDecodeError):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,detail="Memory service unavailable") from None

@router.post("/source/synchronize")
async def synchronize_source(form: SourceSynchronizationRequest,user=Depends(get_verified_user),db: AsyncSession=Depends(get_async_session)):
    chat=await Chats.get_chat_by_id_and_user_id(form.chat_id,user.id,db=db)
    if not chat: raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,detail="Chat not found")
    return await _synchronize_chat(chat,user.id,form.chat_id)

@router.post("/internal/evaluation-wait")
async def evaluation_wait(form: EvaluationWaitRequest,request: Request):
    """B1/B3: the bounded send hold, over the secret-guarded internal surface.

    `prepare_for_chat` calls this before the Core `prepare` and before the model call, so the
    previous turn's evaluation is given a bounded chance to finish before the next send is admitted.
    It is internal rather than browser-facing because the bound must not be negotiable by a client:
    the request's own `maximum_wait_seconds` is clamped here, and the Core clamps it again.

    The turn is never *refused* by this route: an expired bound comes back as `WAIT_TIMEOUT` and the
    caller proceeds, with the skipped evaluation recorded as a coverage gap and no retry (D5).
    """
    expected=_callback_expected_token()
    if not token_matches(_bearer(request),expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,detail="Invalid evaluation callback credential")
    requested=_positive_number_from_payload(form.maximum_wait_seconds,EVALUATION_WAIT_SECONDS)
    try:
        return await asyncio.to_thread(_client,"/v1/memory/manage",{
            "action":"EVALUATION_WAIT","owner_id":form.owner_id,"chat_id":form.chat_id,
            "maximum_wait_seconds":requested,
        },requested+_EVALUATION_WAIT_GRACE_SECONDS)
    except (ChatMemoryClientError,OSError,KeyError,ValueError,RuntimeError,urllib.error.URLError,json.JSONDecodeError):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,detail="Evaluation wait did not complete") from None

@router.post("/internal/evaluated")
async def evaluation_completed(form: EvaluationCompletedRequest,request: Request):
    """H1: the Core says a round's evaluation is terminal; publish it to the owner's browser.

    Server-to-server and loopback-only in practice, guarded by the shared callback secret the
    adapter itself owns -- the Core holds no Open WebUI credential in client-API mode, so it cannot
    present a user session and must not be able to act as one. Nothing here reads or writes memory:
    it publishes a content-free notification, and the client refetches through the ordinary
    authenticated routes.

    A duplicate revision is accepted and *not* republished, which is what makes "exactly one socket
    event per committed evaluation" true even if the push is retried.
    """
    expected=""
    try:
        expected=ensure_callback_token(_callback_data_root())
    except OSError:
        log.warning("Dissipative Memory evaluation push token is unavailable")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,detail="Evaluation callback is unavailable") from None
    if not token_matches(_bearer(request),expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,detail="Invalid evaluation callback credential")
    try:
        published=await publish_evaluation_completed(
            {"user_id":form.owner_id,"chat_id":form.chat_id,"message_id":form.assistant_message_id,"internal":True},
            owner_id=form.owner_id,chat_id=form.chat_id,round_id=form.round_id,
            assistant_message_id=form.assistant_message_id,disposition=form.disposition,
            semantic_revision=form.semantic_revision,evaluation_revision=form.evaluation_revision,
            lifecycle={"event_version":form.event_version,"phase":form.phase,
                       "scope_generation":form.scope_generation,"branch_generation":form.branch_generation,
                       "error_class":form.error_class} if form.event_version==2 else None,
        )
    except Exception as failure:
        # Class name only: the router's logging is constrained to content-free fields.
        error_class=type(failure).__name__
        log.warning("Dissipative Memory evaluation push failed: %s",error_class)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,detail="Evaluation push did not complete") from None
    return {"ok":True,"published":bool(published),"evaluation_revision":int(form.evaluation_revision)}

