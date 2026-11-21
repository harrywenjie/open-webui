"""Exercise the installed candidate in fresh SQLite databases with synthetic identities and a loopback model."""

import argparse
import contextlib
import csv
import hashlib
import importlib.util
from importlib.metadata import distribution
import io
import json
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from uuid import uuid4
from zipfile import ZipFile

from rehearsal_oidc import make_handler

FORK = Path(__file__).resolve().parents[2]
PY = Path(sys.executable)
PORT = 18476
BASE = f"http://127.0.0.1:{PORT}"
ISSUER = "http://127.0.0.1:18479"
CALLBACK = BASE + "/oauth/oidc/login/callback"
PASSWORD = secrets.token_urlsafe(28)
SESSION_KEY = secrets.token_urlsafe(48)
OIDC_SECRET = secrets.token_urlsafe(32)
spec = importlib.util.spec_from_file_location("login_migration", FORK / "downstream/migrate_login.py")
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def env_for(folder):
    env = os.environ.copy()
    # A check against the candidate can only open the fixture database and services.
    env.update(
        DATA_DIR=str(folder),
        DATABASE_URL="sqlite:///" + (folder / "webui.db").as_posix(),
        WEBUI_SECRET_KEY=SESSION_KEY,
        WEBUI_AUTH="true",
        WEBUI_URL=BASE,
        OAUTH_CLIENT_ID="fixture-client",
        OAUTH_CLIENT_SECRET=OIDC_SECRET,
        OPENID_PROVIDER_URL=ISSUER + "/.well-known/openid-configuration",
        OPENID_REDIRECT_URI=CALLBACK,
        OAUTH_TOKEN_ENDPOINT_AUTH_METHOD="client_secret_basic",
        OAUTH_MERGE_ACCOUNTS_BY_EMAIL="false",
        ENABLE_OAUTH_SIGNUP="false",
        OFFLINE_MODE="true",
        HF_HUB_OFFLINE="1",
        ENABLE_OLLAMA_API="false",
        ENABLE_OPENAI_API="true",
        OPENAI_API_BASE_URLS="http://127.0.0.1:18477/v1",
        OPENAI_API_KEYS="synthetic",
        ENABLE_SIGNUP="false",
        ENABLE_LOGIN_FORM="true",
        DEFAULT_MODELS="fixture-model",
        RAG_EMBEDDING_ENGINE="openai",
        RAG_EMBEDDING_MODEL_AUTO_UPDATE="false",
        RAG_RERANKING_MODEL_AUTO_UPDATE="false",
        WHISPER_MODEL_AUTO_UPDATE="false",
        ENABLE_VERSION_UPDATE_CHECK="false",
        DISSIPATIVE_STARTUP_SYNC="0",
        DISSIPATIVE_LIVENESS_ENABLED="0",
        DISSIPATIVE_INSTANCE_ID="owui-rehearsal",
        DISSIPATIVE_LOOPBACK_URL="http://127.0.0.1:18478",
        DISSIPATIVE_OPEN_WEBUI_PORT=str(PORT),
        PYTHONUTF8="1",
        PYTHONDONTWRITEBYTECODE="1",
        HF_HOME=str(LAB / "hf"),
        XDG_CACHE_HOME=str(LAB / "cache"),
        SENTENCE_TRANSFORMERS_HOME=str(LAB / "hf"),
        TOKENIZERS_PARALLELISM="false",
        ANONYMIZED_TELEMETRY="false",
        DO_NOT_TRACK="1",
        NO_PROXY="localhost,127.0.0.1",
        no_proxy="localhost,127.0.0.1",
    )
    env.pop("PYTHONPATH", None)
    return env


def migrate_schema(folder, revision):
    folder.mkdir(parents=True, exist_ok=True)
    env = env_for(folder)
    env["ENABLE_DB_MIGRATIONS"] = "false"
    code = """from importlib.metadata import distribution
from pathlib import Path
from alembic.config import Config
from alembic import command
import sys
pkg=Path(distribution('open-webui').locate_file('open_webui'))
cfg=Config(str(pkg/'alembic.ini'))
cfg.set_main_option('script_location',str(pkg/'migrations'))
command.upgrade(cfg,sys.argv[1])
"""
    with (LAB / ("migrate-" + folder.name + ".log")).open("wb") as log:
        subprocess.run([str(PY), "-c", code, revision], env=env, cwd=LAB, stdout=log, stderr=log, check=True)


def request(path, data=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(BASE + path, data=None if data is None else json.dumps(data).encode(), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def seed_identities(db):
    import bcrypt

    now = int(time.time())
    people = [("admin", "admin", 1), ("member", "user", 1), ("pending", "pending", 1), ("disabled", "user", 0)]
    for name, role, active in people:
        email = name + "@example.org"
        uid = "fixture-" + name
        verifier = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt()).decode()
        db.execute(
            'INSERT INTO user (id,email,name,role,profile_image_url,settings,last_active_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)',
            (uid, email, "Old name", role, "/discard", '{"discard":true}', now, now, now),
        )
        db.execute("INSERT INTO auth(id,email,password,active) VALUES(?,?,?,?)", (uid, email, verifier, active))
    db.execute(
        """UPDATE user SET oauth=? WHERE id='fixture-member'""",
        (json.dumps({"oidc": {"sub": "fixture-subject", "access_token": "discard"}}),),
    )
    db.execute(
        """INSERT INTO "group"(id,user_id,name,description,permissions,created_at,updated_at)
                  VALUES('fixture-group','fixture-admin','Fixture group','discard',?,?,?)""",
        ('{"workspace":{"tools":true}}', now, now),
    )
    db.execute(
        "INSERT INTO config(key,value,updated_at) VALUES('user.permissions',?,?)",
        ('{"workspace":{"tools":false},"chat":{"delete":false}}', now),
    )
    db.execute(
        "INSERT INTO group_member(id,group_id,user_id,created_at,updated_at) VALUES('gm','fixture-group','fixture-member',?,?)",
        (now, now),
    )
    db.execute(
        "INSERT INTO chat(id,user_id,title,chat,created_at,updated_at) VALUES('old-chat','fixture-member','discard','{}',?,?)",
        (now, now),
    )
    db.execute(
        "INSERT INTO file(id,user_id,filename,created_at,updated_at) VALUES('old-file','fixture-member','discard',?,?)",
        (now, now),
    )
    db.commit()


def provision_theme(target):
    subprocess.run([str(PY), str(THEME / "build_theme.py"), "--check"], check=True)
    policy = json.loads((CORE / "integrations/open-webui/updater/reference/integration-policy.json").read_bytes())

    def locate(data):
        if isinstance(data, dict):
            if data.get("id") == "theme_designer_pro":
                yield data
            for value in data.values():
                yield from locate(value)
        elif isinstance(data, list):
            for value in data:
                yield from locate(value)

    (contract,) = locate(policy)
    assert digest(FUNC) == contract["content_sha256"]
    out = target / "theme"
    out.mkdir(exist_ok=True)
    names = (
        "open_theme_designer.css",
        "open_theme_designer.json",
        "open_theme_designer_sections.json",
        "open_theme_designer_library.json",
    )
    for name in names:
        src = THEME / "generated" / name
        shutil.copyfile(src, out / name)
        assert digest(src) == digest(out / name)
    now = int(time.time())
    with contextlib.closing(sqlite3.connect(target / "webui.db")) as db, db:
        db.execute(
            """INSERT INTO function(id,user_id,name,type,content,meta,valves,is_active,is_global,created_at,updated_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "theme_designer_pro",
                "fixture-admin",
                "Theme Designer Pro",
                "event",
                FUNC.read_text(encoding='utf8'),
                json.dumps({"manifest": {"version": "1.8.0"}}),
                json.dumps(contract["valves"]),
                1,
                0,
                now,
                now,
            ),
        )
        meta = json.dumps({"toolIds": ["dissipative_remember"]})
        db.execute(
            "INSERT INTO model(id,user_id,base_model_id,name,meta,params,is_active,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
            ("fixture-model", "fixture-admin", None, "Rehearsal model", meta, "{}", 1, now, now),
        )
        tool = (CORE / "integrations/open-webui/tools/remember.py").read_text(encoding="utf8")
        db.execute(
            "INSERT INTO tool(id,user_id,name,content,specs,meta,is_active,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
            ("dissipative_remember", "fixture-admin", "Dissipative Memory", tool, "[]", "{}", 1, now, now),
        )
    return {name: digest(out / name) for name in names}


def signin(name):
    status, data = request("/api/v1/auths/signin", {"email": name + "@example.org", "password": PASSWORD})
    return status, json.loads(data)


def api_checks():
    from requests import Session

    roles = {}
    for name, role in (("admin", "admin"), ("member", "user"), ("pending", "pending"), ("disabled", None)):
        status, data = signin(name)
        if role is None:
            assert status in (400, 401, 403) and not data.get("token"), (name, status)
            roles[name] = "DENIED"
        else:
            assert status == 200 and data["role"] == role and data["id"] == "fixture-" + name, (name, status)
            assert data["permissions"]["chat"]["delete"] is False
            assert data["permissions"]["workspace"]["tools"] == (name == "member")
            assert all(data["permissions"][section][key] is False for section, key in migration.NEW_PERMISSIONS)
            status, _ = request("/api/v1/chats/", token=data["token"])
            assert status == 200 if role != "pending" else status in (401, 403), (name, status)
            roles[name] = role
    with Session() as session:
        session.trust_env = False
        response = session.get(BASE + "/oauth/oidc/login", timeout=12)
        assert response.status_code == 200, ("OIDC callback", response.status_code)
        response = session.get(BASE + "/api/v1/auths/", timeout=12)
        assert response.status_code == 200, ("OIDC session", response.status_code)
        identity = response.json()
        assert (identity["id"], identity["role"]) == ("fixture-member", "user")
        assert identity["permissions"]["workspace"]["tools"] is True
        roles["member_oidc"] = "user"
    code, body = request("/api/version")
    adapter = json.loads((FORK / "downstream/adapter.json").read_text(encoding="utf8"))["adapter_version"]
    assert code == 200 and json.loads(body)["deployment_id"] == adapter
    for url, marker in (
        ("/static/custom.css", b"owui-theme-designer-pro"),
        ("/static/loader.js", b"owui-theme-designer-pro"),
        ("/api/v1/theme-designer/theme.css", b"--ops-canvas"),
        ("/api/v1/theme-designer/state.json", b"dark"),
    ):
        code, body = request(url)
        assert code == 200 and marker.lower() in body.lower(), (url, code, len(body))
    subprocess.run([str(PY), str(FORK / "downstream/verify_branding.py"), "--url", BASE], check=True)
    return roles


@contextlib.contextmanager
def server(target, number):
    log = (LAB / f"webui-{number}.log").open("wb")
    process = subprocess.Popen(
        [
            str(PY),
            "-m",
            "uvicorn",
            "open_webui.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(PORT),
            "--no-access-log",
        ],
        env=env_for(target),
        cwd=LAB,
        stdout=log,
        stderr=log,
    )
    log.close()
    try:
        for _ in range(180):
            if process.poll() is not None:
                raise RuntimeError(f"Candidate startup exited {process.returncode}, see webui-{number}.log")
            try:
                if request("/health")[0] == 200:
                    break
            except OSError:
                pass
            time.sleep(1)
        else:
            raise RuntimeError("Candidate startup timed out")
        yield process
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=30)


def run():
    from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
    import threading

    installed = distribution("open-webui")
    installed_hashes = {name: checksum for name, checksum, _ in csv.reader(io.StringIO(installed.read_text("RECORD")))}
    with ZipFile(ARTIFACT) as archive:
        (record,) = (name for name in archive.namelist() if name.endswith(".dist-info/RECORD"))
        for name, checksum, _ in csv.reader(io.StringIO(archive.read(record).decode("utf-8"))):
            if checksum and installed_hashes.get(name) != checksum:
                raise RuntimeError(f"Installed package differs from the wheel at {name}")
    LAB.mkdir(parents=True, exist_ok=False)
    batch = LAB
    source, target = batch / "old", batch / "new"
    migrate_schema(source, migration.SOURCE)
    migrate_schema(target, migration.TARGET)
    with contextlib.closing(sqlite3.connect(source / "webui.db")) as db:
        seed_identities(db)
    bundle = batch / "admission.sqlite"
    migration.export_login(source / "webui.db", bundle)
    result = migration.import_login(bundle, target / "webui.db")
    assert migration.import_login(bundle, target / "webui.db")["result"] == "ALREADY_IMPORTED"
    with contextlib.closing(sqlite3.connect(target / "webui.db")) as db:
        zero = {
            name: db.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
            for name, in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")
            if name not in {"config", "alembic_version", *migration.TABLES} and not name.startswith("sqlite_")
        }
        assert not any(zero.values())
    theme = provision_theme(target)

    class Models(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            body = json.dumps(
                {"object": "list", "data": [{"id": "fixture-model", "object": "model", "owned_by": "fixture"}]}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.path != "/v1/chat/completions":
                return self.send_error(404)
            form = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            answer = "Rehearsal response from the local model."
            common = {"id": "synthetic-completion", "created": int(time.time()), "model": "fixture-model"}
            self.send_response(200)
            if form.get("stream"):
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for text, reason in (("Rehearsal response ", None), ("from the local model.", None), ("", "stop")):
                    choice = {"index": 0, "delta": {"content": text}, "finish_reason": reason}
                    chunk = {**common, "object": "chat.completion.chunk", "choices": [choice]}
                    self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
                    self.wfile.flush()
                self.wfile.write(b"data: [DONE]\n\n")
            else:
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                choice = {"index": 0, "message": {"role": "assistant", "content": answer}, "finish_reason": "stop"}
                self.wfile.write(json.dumps({**common, "object": "chat.completion", "choices": [choice]}).encode())

    issuer_handler = make_handler(ISSUER, CALLBACK, OIDC_SECRET)
    with (
        ThreadingHTTPServer(("127.0.0.1", 18477), Models) as models,
        ThreadingHTTPServer(("127.0.0.1", 18479), issuer_handler) as issuer,
    ):
        threading.Thread(target=models.serve_forever, daemon=True).start()
        threading.Thread(target=issuer.serve_forever, daemon=True).start()
        try:
            for number in (1, 2):
                with server(target, number):
                    roles = api_checks()
                    pkg = installed.locate_file("open_webui")
                    subprocess.run(
                        [str(PY), str(FORK / "downstream/verify_branding.py"), "--installed", str(pkg)], check=True
                    )
                    env = {
                        **os.environ,
                        "OWUI_FIXTURE_PASSWORD": PASSWORD,
                        "OWUI_PROBE_RUN": str(number),
                        "OWUI_SCREENSHOTS": str(batch),
                        "OWUI_THEME_DEFINITION": str(THEME / "theme-definition.json"),
                    }
                    with (LAB / f"browser-{number}.log").open("wb") as log:
                        subprocess.run(
                            [
                                "node",
                                str(BROWSER),
                                "--url",
                                BASE,
                                "--script",
                                str(Path(__file__).with_name("upgrade-appearance.mjs")),
                                "--text-chars",
                                "0",
                                *(["--storage", str(batch / "theme-choice.json")] if number == 2 else []),
                            ],
                            env=env,
                            stdout=log,
                            stderr=log,
                            check=True,
                        )
                    chat_path = json.loads((batch / "chat-path.json").read_text(encoding="utf-8"))
                    chat_id = chat_path.split("/")[-1]
                    member = signin("member")[1]
                    denied, _ = request("/api/v1/chats/" + chat_id, token=member["token"])
                    assert denied in {401, 403, 404}, ("cross-user chat read", denied)
        finally:
            issuer.shutdown()
            models.shutdown()
    summary = {
        "wheel": digest(ARTIFACT),
        "migration": result,
        "empty": zero,
        "logins": roles,
        "theme": theme,
        "browser_runs": 2,
        "new_chat": {"stream": "complete", "restart_read": True, "other_user_read": "denied"},
        "evidence": batch.name,
    }
    (LAB / "result.json").write_text(json.dumps(summary, indent=2), encoding="utf8")
    print(json.dumps(summary))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name, help_text in (
        ("wheel", "The candidate wheel installed in this interpreter's dedicated environment"),
        ("output", "Parent directory for a fresh rehearsal batch and its private logs"),
        ("core-source", "Dissipative candidate checkout with reviewed policy and tool"),
        ("theme-source", "Versioned theme directory containing build_theme.py"),
        ("theme-function", "Reviewed Theme Designer Pro Python source"),
        ("browser-runner", "Playwright pw.mjs driver accepting --url and --script"),
    ):
        parser.add_argument("--" + name, type=Path, required=True, help=help_text)
    args = parser.parse_args()
    ARTIFACT, CORE = args.wheel.resolve(), args.core_source.resolve()
    THEME, FUNC = args.theme_source.resolve(), args.theme_function.resolve()
    BROWSER = args.browser_runner.resolve()
    LAB = args.output.resolve() / ("fixture-" + uuid4().hex[:10])
    run()
