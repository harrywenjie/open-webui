"""Exercise a fresh, loopback-only WebUI/Core pair. Real Qwen is an explicit test option."""

import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.metadata import distribution
from uuid import uuid4

import rehearse_install as install

INSTANCE = "webui-continuity-candidate"
MODEL = "Qwen-Custom"
CORE_URL = "http://127.0.0.1:18478"
ID = "fixture-admin"
FILTERS = ["dissipative_filter", "dissipative_fast_answer_finalizer", "dissipative_events"]
MARKER = "cobalt-tamarind-726"


def encoded(value):
    return json.dumps(value, ensure_ascii=False).encode()


def http(url, body=None, token=None, method=None, timeout=60):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, None if body is None else encoded(body), headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def ok(response):
    code, raw = response
    if code != 200:
        try:
            detail = json.loads(raw).get("detail") or json.loads(raw).get("error")
        except (ValueError, AttributeError):
            detail = None
        safe = detail if isinstance(detail, str) and len(detail) < 150 else "HTTP_FAILURE"
        raise AssertionError((code, safe))
    return json.loads(raw)


def provision(folder, core):
    import bcrypt

    install.migrate_schema(folder, "9f6c2a8d1b43")
    now = int(time.time())
    with sqlite3.connect(folder / "webui.db") as db:
        for name, role in [("admin", "admin"), ("member", "user")]:
            uid = "fixture-" + name
            email = name + "@example.org"
            password = bcrypt.hashpw(install.PASSWORD.encode(), bcrypt.gensalt()).decode()
            db.execute("INSERT INTO user(id,email,name,role,profile_image_url,settings,last_active_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                       (uid, email, name, role, "/user.png", '{"ui":{"regenerateMenu":false}}', now, now, now))
            db.execute("INSERT INTO auth(id,email,password,active) VALUES(?,?,?,1)", (uid, email, password))
    install.provision_theme(folder)
    with sqlite3.connect(folder / "webui.db") as db:
        for name in FILTERS:
            content = (core / ("integrations/open-webui/functions/" + name + ".py")).read_text(encoding="utf8")
            kind = "event" if name == "dissipative_events" else "filter"
            db.execute("INSERT INTO function(id,user_id,name,type,content,meta,valves,is_active,is_global,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (name, ID, name, kind, content, "{}", "{}", 1, 0, now, now))
        specs = (core / "integrations/open-webui/updater/reference/test-fixtures/remember-specs.json").read_text()
        db.execute("UPDATE tool SET specs=? WHERE id='dissipative_remember'", (specs,))
        db.execute("UPDATE model SET id=?,name=?,meta=?,params=? WHERE id='fixture-model'",
                   (MODEL, MODEL, json.dumps({"filterIds": FILTERS, "defaultFilterIds": FILTERS,
                    "toolIds": ["dissipative_remember"], "defaultFeatureIds": []}), '{"function_calling":"native"}'))


class ModelRelay:
    """Keep credentials in this process. Count and bound real calls before forwarding synthetic inputs."""
    def __init__(self, connection):
        self.connection = connection
        self.calls = []
        self.lock = threading.Lock()
        self.keys = {lane: secrets.token_urlsafe(32) for lane in ("chat", "core")}

    def handler(self):
        relay = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, status, payload, content_type="application/json"):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self):
                self.reply(200, encoded({"object": "list", "data": [{"id": MODEL, "object": "model", "owned_by": "fixture"}]}))

            def do_POST(self):
                lane = "core" if self.path == "/core/v1/chat/completions" else "chat"
                if self.path not in {"/core/v1/chat/completions", "/v1/chat/completions"} or not secrets.compare_digest(
                        self.headers.get("Authorization", ""), "Bearer " + relay.keys[lane]):
                    return self.reply(403, b"{}")
                size = int(self.headers.get("Content-Length", 0))
                if not 0 < size <= 1024 * 1024:
                    return self.reply(413, b"{}")
                wire = self.rfile.read(size)
                body = json.loads(wire)
                if body.get("model") != MODEL:
                    return self.reply(400, b"{}")
                core = self.path.startswith("/core/")
                role = "curator" if b"CURATOR_INPUT_DATA" in wire and core else "reader" if core else "chat"
                row = {"role": role, "request_bytes": size, "request_sha256": hashlib.sha256(wire).hexdigest(),
                       "chat_filter": b"chat-memory-control" in wire, "stream": bool(body.get("stream"))}
                if role == "curator":
                    row["technical_profile_guidance"] = b"technical" in wire and b"global_guidance" in wire
                with relay.lock:
                    if relay.connection and sum(r["role"] == role for r in relay.calls) >= {"curator": 2, "reader": 2, "chat": 6}[role]:
                        return self.reply(429, b'{"error":"QUALIFICATION_BUDGET"}')
                    relay.calls.append(row)
                if relay.connection:
                    endpoint, key = relay.connection
                    req = urllib.request.Request(endpoint, wire, {"Authorization": "Bearer " + key, "Content-Type": "application/json"})
                    try:
                        with urllib.request.urlopen(req, timeout=115) as resp:
                            payload = resp.read(4 * 1024 * 1024)
                            row["status"] = resp.status
                            return self.reply(resp.status, payload, resp.headers.get_content_type())
                    except Exception as exc:
                        row["error"] = type(exc).__name__
                        return self.reply(502, b'{"error":"UPSTREAM_UNAVAILABLE"}')
                if core:
                    row["status"] = 503
                    return self.reply(503, b'{"error":"LOCAL_MODEL_HAS_NO_CURATOR"}')
                answer = f"Local rehearsal reply {len(relay.calls)}."
                if body.get("messages", [{}])[-1].get("role") == "assistant":
                    answer = " The continuation adds a second sentence."
                common = {"id": "fixture-response", "created": int(time.time()), "model": MODEL}
                if body.get("stream"):
                    chunks = [dict(common, object="chat.completion.chunk", choices=[{"index": 0, "delta": delta, "finish_reason": stop}])
                              for delta, stop in [({"role": "assistant", "content": answer}, None), ({}, "stop")]]
                    return self.reply(200, b"".join(b"data: " + encoded(c) + b"\n\n" for c in chunks) + b"data: [DONE]\n\n", "text/event-stream")
                self.reply(200, encoded(dict(common, object="chat.completion", choices=[{"index": 0,
                    "message": {"role": "assistant", "content": answer}, "finish_reason": "stop"}])))
        return Handler


@contextlib.contextmanager
def service(args, env, log, ready):
    with log.open("wb") as output:
        proc = subprocess.Popen(args, cwd=log.parent, env=env, stdout=output, stderr=output)
    try:
        for _ in range(180):
            if proc.poll() is not None:
                raise RuntimeError(f"{log.name} exited {proc.returncode}")
            try:
                if ready():
                    break
            except OSError:
                pass
            time.sleep(1)
        else:
            raise RuntimeError(f"{log.name} startup timeout")
        yield
    finally:
        if proc.poll() is None:
            proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)


async def check_fast_barrier(chat, user, assistant, issued, action):
    """Drive the installed Tool seam with one synthetic, server-owned attempt across a restart."""
    from open_webui.routers.dissipative_memory import fast_for_chat

    result = await fast_for_chat(ID, chat, action, {
        "current_message_id": user, "assistant_message_id": assistant, "request_id": "message:" + assistant,
        "request_issued_at": float(issued), "candidate_model_id": MODEL, "integration_id": "dissipative-fast-client-v1",
        "memory_request_kind": "EXPLICIT_MEMORY_ONLY", "task_handoff": "",
    })
    if action == "cancel":
        assert result["state"] == "CANCEL_REQUESTED"
    else:
        assert not result.get("publication_handle")


def verify_fast_barrier(lab, web_env, number, result):
    chat, user, assistant = json.loads((lab / "client-chat.json").read_text())
    clock = lab / "cancel-issued.json"
    if number == 1:
        clock.write_text(json.dumps(time.time()))
    command = "import asyncio,sys; from qualify_continuity import check_fast_barrier; asyncio.run(check_fast_barrier(*sys.argv[1:]))"
    subprocess.run([sys.executable, "-c", command, chat, user, assistant, clock.read_text(),
                    "cancel" if number == 1 else "answer"], cwd=Path(__file__).parent, env=web_env,
                   check=True, stdout=subprocess.DEVNULL, timeout=60)
    with sqlite3.connect(lab / "core.db") as db:
        state = db.execute("SELECT state,dispatch_count FROM fast_request_attempts WHERE chat_id=? AND request_id=?",
                           (chat, "message:" + assistant)).fetchall()
    assert state == [("CANCELLED", 0)], state
    result["checks"]["fast_cancel_before_dispatch" if number == 1 else "fast_cancel_survived_restart"] = True


def verify_saved_fast(lab, key, result):
    """Recheck the browser's actual publication against an edit to its original source."""
    state = json.loads((lab / "browser-chat.json").read_text(encoding="utf8"))
    token = ok(install.request("/api/v1/auths/signin", {"email": "admin@example.org", "password": install.PASSWORD}))["token"]
    chat = state["path"].split("/")[-1]
    route = install.BASE + "/api/v1/chats/" + chat
    history = ok(http(route, token=token))["chat"]["history"]["messages"]
    final = history[state["final"]]
    call = next(i for i in final["output"] if i.get("name") == "answer_from_chat_memory_v2")
    envelope = next(i for i in final["output"] if i["type"] == "function_call_output" and i["call_id"] == call["call_id"])
    handle = json.loads(envelope["output"][0]["text"])["publication_handle"]
    with sqlite3.connect(lab / "core.db") as db:
        current, dispatches = db.execute("SELECT current_message_id,dispatch_count FROM fast_request_attempts "
            "WHERE instance_id=? AND owner_id=? AND chat_id=? AND assistant_message_id=?", (INSTANCE, ID, chat, final["id"])).fetchone()
    assert dispatches == 1
    boundary = dict(api_version="dissipative.client.v1", protocol="dissipative.continuity.v2",
        transport_version="dissipative.continuity.transport.v1", instance_id=INSTANCE, owner_id=ID, chat_id=chat,
        request_id="message:" + final["id"], current_message_id=current, assistant_message_id=final["id"],
        candidate_model_id=MODEL, integration_id="dissipative-fast-client-v1", call_id=call["call_id"], publication_handle=handle)
    def publication():
        return ok(http(CORE_URL + "/v1/continuity/fast-answer/publication", boundary, key))["result"]
    before = publication()
    if before["state"] == "READY":
        assert before["answer_markdown"] == state["answer"]
    original = next(m for m in history.values() if m["role"] == "user" and MARKER in m["content"])
    ok(http(route + "/messages/" + original["id"], {"content": "The earlier marker was withdrawn."}, token))
    after = publication()
    assert after["state"] != "READY" and MARKER not in str(after.get("answer_markdown") or "")
    result["checks"]["fast_publication_revalidation"] = {"after_restart": before["state"], "after_source_edit": after["state"],
                                                        "reader_dispatches": dispatches}


def run(args):
    global CORE_URL
    install.PORT = args.webui_port
    install.BASE = f"http://127.0.0.1:{install.PORT}"
    model_port, core_port = install.PORT + 1, install.PORT + 2
    CORE_URL = f"http://127.0.0.1:{core_port}"
    for port in (install.PORT, model_port, core_port):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", port))
    core, lab = args.core_source.resolve(), args.output.resolve() / ("pair-" + uuid4().hex[:10])
    lab.mkdir(parents=True)
    if os.name == "nt":
        account = subprocess.check_output(["whoami"], text=True).strip()
        subprocess.run(["icacls", str(lab), "/inheritance:r", "/grant:r", account + ":(OI)(CI)F"],
                       check=True, stdout=subprocess.DEVNULL)
    else:
        lab.chmod(0o700)
    print("Fixture", lab.name, flush=True)
    install.LAB, install.CORE = lab, core
    install.THEME, install.FUNC = args.theme_source.resolve(), args.theme_function.resolve()
    sys.path[:0] = [str(core / "src"), str(core / "tests/qualification")]
    from dissipative_core.api_key_store import ApiKeyStore
    from provider_support import connection

    result = {"schema": 34, "real": args.real, "checks": {}}
    relay = ModelRelay(connection(os.environ["DISSIPATIVE_CREDENTIAL_FILE"], MODEL) if args.real else None)
    folder = lab / "webui"
    provision(folder, core)
    package = Path(distribution("open-webui").locate_file("open_webui"))
    shutil.copytree(package / "static", folder / "static")
    registry = lab / "instance-keys.json"
    key, _ = ApiKeyStore(registry).create("webui-candidate", instance_ids={INSTANCE}, scopes={"memory:read", "memory:write"})
    key_file = lab / "instance.key"
    key_file.write_text(key, encoding="utf8")
    model_url = f"http://127.0.0.1:{model_port}"
    core_env = dict(os.environ, DISSIPATIVE_MODEL_ENDPOINT=model_url + "/core/v1/chat/completions",
                    DISSIPATIVE_MODEL_MODEL=MODEL, DISSIPATIVE_MODEL_API_KEY=relay.keys["core"], PYTHONUTF8="1")
    core_args = [sys.executable, str(core / "scripts/run-service.py"), "--database", str(lab / "core.db"),
                 "--log", str(lab / "core.log"), "--port", str(core_port), "--open-webui", install.BASE, "--api-key-registry", str(registry),
                 "--curator", "model", "--curator-scheduling-protocol", "4", "--model-invocation-profile", "qwen-custom@2",
                 "--enable-continuity-transport", "--enable-round-curation", "--enable-profile-selection",
                 "--enable-profile-publication", "--enable-source-format-transition", "--enable-retrieval-fast-first-release",
                 "--curator-max-in-flight", "1", "--reconcile-seconds", "1",
                 "--evaluation-callback-token-file", str(folder / ".fixture-callback")]
    invalid = subprocess.run(core_args + ["--model-admin-store", str(lab / "invalid-catalog")], env=core_env, capture_output=True)
    assert invalid.returncode == 2 and b"no managed catalog" in invalid.stderr and not (lab / "core.db").exists()
    result["checks"]["managed_catalog_rejected_before_database"] = True
    web_env = install.env_for(folder)
    for k in ("OAUTH_CLIENT_ID", "OAUTH_CLIENT_SECRET", "OPENID_PROVIDER_URL", "OPENID_REDIRECT_URI"):
        web_env.pop(k, None)
    web_env.update(DISSIPATIVE_CONTINUITY="1", DISSIPATIVE_INSTANCE_ID=INSTANCE, DISSIPATIVE_LIVENESS_SYNC="0",
                   WEBUI_URL=install.BASE, DISSIPATIVE_LOOPBACK_URL=CORE_URL, DISSIPATIVE_OPEN_WEBUI_PORT=str(install.PORT),
                   OPENAI_API_BASE_URLS=model_url + "/v1", STATIC_DIR=str(folder / "static"),
                   DISSIPATIVE_STARTUP_SYNC="1", DISSIPATIVE_API_KEY_FILE=str(key_file), OPEN_WEBUI_DATA_DIR=str(folder),
                   DEFAULT_MODELS=MODEL, OPENAI_API_KEYS=relay.keys["chat"], ENABLE_TITLE_GENERATION="false", ENABLE_TAGS_GENERATION="false",
                   ENABLE_FOLLOW_UP_GENERATION="false")
    if args.source_backend:
        web_env["PYTHONPATH"] = str(install.FORK / "backend")
        web_env["FRONTEND_BUILD_DIR"] = str(package / "frontend")
    web_args = [sys.executable, "-m", "uvicorn", "open_webui.main:app", "--host", "127.0.0.1",
                "--port", str(install.PORT), "--no-access-log"]
    try:
        with ThreadingHTTPServer(("127.0.0.1", model_port), relay.handler()) as listener:
            threading.Thread(target=listener.serve_forever, daemon=True).start()
            try:
                for run_number in (1, 2):
                    with service(core_args, core_env, lab / f"core-{run_number}.log",
                                 lambda: http(CORE_URL + "/v1/health", token=key)[0] == 200), service(
                            web_args, web_env, lab / f"webui-{run_number}.log", lambda: http(install.BASE + "/health")[0] == 200):
                        with sqlite3.connect(lab / "core.db") as db:
                            assert db.execute("PRAGMA user_version").fetchone()[0] == 34
                            if run_number == 1:
                                assert db.execute("SELECT count(*) FROM scopes").fetchone() == (0,)
                        verify(args, lab, key, result, run_number, web_env)
                        if args.browser_runner:
                            env = dict(os.environ, OWUI_FIXTURE_PASSWORD=install.PASSWORD, OWUI_SCREENSHOTS=str(lab),
                                       OWUI_PROBE_RUN=str(run_number), OWUI_REAL=str(int(args.real)))
                            with (lab / f"browser-{run_number}.log").open("wb") as log:
                                subprocess.run(["node", str(args.browser_runner), "--url", install.BASE,
                                    "--script", str(Path(__file__).with_name("continuity-chat.mjs")), "--text-chars", "0"],
                                    env=env, stdout=log, stderr=log, timeout=430, check=True)
                            result["checks"]["browser_" + str(run_number)] = "PASS"
                            if args.real and run_number == 2:
                                count = len(relay.calls)
                                verify_saved_fast(lab, key, result)
                                assert len(relay.calls) == count
            finally:
                listener.shutdown()
    finally:
        result["model_calls"] = relay.calls
        (lab / "result.json").write_text(json.dumps(result, indent=2), encoding="utf8")
    print(json.dumps(result["checks"], ensure_ascii=False))


def verify(args, lab, key, result, number, web_env):
    assert ok(http(install.BASE + "/api/version"))["deployment_id"] == "dissipative-adapter-4.22"
    subprocess.run([sys.executable, str(install.FORK / "downstream/verify_branding.py"), "--url", install.BASE],
                   check=True, stdout=subprocess.DEVNULL)
    result["checks"]["adapter_identity_and_served_icons"] = True
    token = ok(install.request("/api/v1/auths/signin", {"email": "admin@example.org", "password": install.PASSWORD}))["token"]
    member = ok(install.request("/api/v1/auths/signin", {"email": "member@example.org", "password": install.PASSWORD}))["token"]
    chat_path = lab / "client-chat.json"
    if number == 1:
        u, a = uuid4().hex, uuid4().hex
        history = {"currentId": a, "messages": {
            u: {"id": u, "parentId": None, "childrenIds": [a], "role": "user", "content": "The Lantern project's confirmed marker is " + MARKER + "."},
            a: {"id": a, "parentId": u, "childrenIds": [], "role": "assistant", "content": "Lantern marker recorded.", "done": True, "model": MODEL}}}
        record = ok(install.request("/api/v1/chats/new", {"chat": {"title": "Continuity fixture", "models": [MODEL], "history": history}}, token))
        chat = record["id"]
        chat_path.write_text(json.dumps([chat, u, a]))
        ok(install.request("/api/v1/chats/" + chat, {"chat": {"history": history}}, token))
    else:
        chat, u, a = json.loads(chat_path.read_text())
    def manage(action, payload=None, who=token):
        return install.request("/api/v1/dissipative/manage", {"chat_id": chat, "action": action, "payload": payload or {}}, who)
    def core_call(route, **fields):
        envelope = dict(api_version="dissipative.client.v1", protocol="dissipative.continuity.v2",
                        transport_version="dissipative.continuity.transport.v1", instance_id=INSTANCE, owner_id=ID, chat_id=chat)
        return ok(http(CORE_URL + "/v1/continuity/" + route, {**fields, **envelope}, key))["result"]
    def search(word):
        return core_call("recall", operation="SEARCH", query=word, request_id=uuid4().hex)
    caps = ok(manage("CONTINUITY_CAPABILITIES"))
    assert caps["source-format-transition"]["schema"] == 34 and caps["capabilities"]["fastReader"] == "ENABLED"
    assert manage("SELECTION_GET", who=member)[0] == 404
    inspected = ok(manage("FORMAT_INSPECT"))
    assert inspected["snapshotHash"].startswith("sha256:") and inspected["metadataHash"].startswith("sha256:")
    assert manage("FORMAT_INSPECT", who=member)[0] == 404
    status = ok(manage("STATUS"))
    assert status.get("continuity") is True, status.get("state")
    with sqlite3.connect(lab / "core.db") as db:
        archive = db.execute("SELECT count(*) FROM round_curation_requests WHERE kind='ARCHIVE' AND chat_id=?", (chat,)).fetchone()[0]
        assert archive == 1, archive
    result["checks"]["empty_core_capabilities_owner_and_archive"] = True
    if number == 1:
        selection = ok(manage("SELECTION_GET"))["selection"]
        none = dict(requestId="none", mode="NONE", expectedSelectionRevision=selection["selection_revision"])
        receipt = ok(manage("SELECTION_SET", none))
        assert receipt["selection"]["mode"] == "NONE" and ok(manage("SELECTION_SET", none))["replayed"]
        assert ok(manage("SELECTION_GET", {"requestId": "none"}))["receipt"]["payloadDigest"] == receipt["payloadDigest"]
        assert manage("SELECTION_SET", {**none, "requestId": "stale"})[0] == 409
        assert ok(manage("PUBLICATION_GET"))["fields"] == []
        assert search(MARKER)["results"]
        result["checks"]["none_keeps_archive_recall"] = True
        selected = ok(manage("SELECTION_SET", dict(requestId="technical", mode="SELECTED", profile_id="technical",
                     profile_revision=1, expectedSelectionRevision=receipt["selection"]["selection_revision"])))
        assert selected["selection"]["profile_id"] == "technical"
        result["checks"]["profile_cas_ack_none_selected"] = True
        if not args.real:
            verify_fast_barrier(lab, web_env, number, result)
        if args.real:
            req = {"requestId": "fixture-curation"}
            accepted = ok(manage("CURATION_ADMIT", req))
            assert accepted["batchCount"] == 1 and ok(manage("CURATION_ADMIT", req))["replayed"]
            for _ in range(150):
                job = ok(manage("CURATION_STATUS", req))
                if job["state"] in ("COMMITTED", "FAILED", "UNKNOWN", "PARTIAL", "DEGRADED"):
                    break
                time.sleep(1)
            result["checks"]["real_curation"] = {"state": job["state"], "covered": len(job["publishedCoverage"])}
            assert job["state"] == "COMMITTED" and len(job["publishedCoverage"]) == 2, job["state"]
    else:
        assert ok(manage("SELECTION_GET"))["selection"]["profile_id"] == "technical"
        result["checks"]["restarted_core_webui_profile_and_archive"] = True
        assert search(MARKER)["results"]
        if not args.real:
            verify_fast_barrier(lab, web_env, number, result)
        if args.real:
            job = ok(manage("CURATION_STATUS", {"requestId": "fixture-curation"}))
            assert job["state"] == "COMMITTED" and len(job["publishedCoverage"]) == 2
            publication = ok(manage("PUBLICATION_GET"))
            assert publication["selection"]["profile_id"] == "technical"
            available = [f for f in publication["fields"] if f["availability"] == "AVAILABLE"]
            for field in available:
                origin = field["publication"]
                assert origin["jobId"] and origin["inputHash"] and origin["responseHash"] and field["supportingSources"]
                historical = ok(manage("PUBLICATION_GET", {"jobId": origin["jobId"]}))
                assert any(f["fieldId"] == field["fieldId"] and f["value"] == field["value"] for f in historical["fields"])
            result["checks"]["restarted_curation_and_publication"] = {
                "covered": 2, "fields": len(publication["fields"]), "attributed_fields": len(available)}
        route = install.BASE + "/api/v1/chats/" + chat
        # Grant and revoke using the actual share routes; memory remains owner-scoped throughout.
        share = ok(http(route + "/share", {}, token))
        grant_route = install.BASE + "/api/v1/chats/shared/" + chat + "/access/update"
        ok(http(grant_route, {"access_grants": [{"principal_type": "user", "principal_id": "fixture-member", "permission": "read"}]}, token))
        shared = install.BASE + "/api/v1/chats/share/" + share["share_id"]
        assert http(shared, token=member)[0] == 200 and manage("SELECTION_GET", who=member)[0] == 404
        before = ok(manage("STATUS"))["authorization_revision"]
        ok(http(route + "/share", token=token, method="DELETE"))
        assert http(shared, token=member)[0] in (401, 403, 404)
        assert ok(manage("STATUS"))["authorization_revision"] > before
        if args.real:
            assert ok(manage("CURATION_STATUS", {"requestId": "fixture-curation"}))["publishedCoverage"] == []
        result["checks"]["shared_grant_revoked"] = True
        record = ok(http(route, token=token))
        history = record["chat"]["history"]
        # New sibling followed by an in-place edit, using the WebUI persistence endpoints.
        sibling = uuid4().hex
        history["messages"][u]["childrenIds"].append(sibling)
        history["messages"][sibling] = dict(history["messages"][a], id=sibling, content="amethyst-zinnia-sibling")
        history["currentId"] = sibling
        ok(http(route, {"chat": {"history": history}}, token))
        assert search("amethyst-zinnia-sibling")["results"]
        ok(http(route + "/messages/" + sibling, {"content": "copper-azalea-edited"}, token))
        assert search("copper-azalea-edited")["results"]
        assert "amethyst-zinnia-sibling" not in json.dumps(search("amethyst-zinnia-sibling")["results"])
        history = ok(http(route, token=token))["chat"]["history"]
        history["currentId"] = a
        ok(http(route, {"chat": {"history": history}}, token))
        assert "copper-azalea-edited" not in json.dumps(search("copper-azalea-edited")["results"])
        result["checks"]["edit_and_branch_recall_fences"] = True
        ok(http(route, token=token, method="DELETE"))
        assert manage("STATUS")[0] == 404
        scope = {"instance_id": INSTANCE, "owner_id": ID, "chat_id": chat}
        preimage = {"version": "dissipative.continuity.deletion.v1", "scope": scope, "effect": "PERMANENT_SCOPE_DELETE"}
        identity = "sha256:" + hashlib.sha256(json.dumps(preimage, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        deletion = core_call("deletion/status", deletion_version=preimage["version"], operationHash=identity)
        assert deletion["logicalState"] == "LOGICALLY_COMPLETE"
        result["checks"]["owner_deletion_tombstone"] = True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("core-source", "output", "theme-source", "theme-function"):
        parser.add_argument("--" + flag, type=Path, required=True)
    parser.add_argument("--source-backend", action="store_true", help="Developer preflight using the candidate backend source")
    parser.add_argument("--browser-runner", type=Path)
    parser.add_argument("--webui-port", type=int, default=18476)
    parser.add_argument("--real", action="store_true", help="Permit bounded calls through the configured Qwen connection")
    run(parser.parse_args())
