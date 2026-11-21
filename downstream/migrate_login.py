"""Transfer only admission data between the two reviewed SQLite schemas.

Run with the writers stopped. Export directly into a protected directory on the
host. Import into a database initialized by the candidate before opening it to
traffic. Both commands print aggregate counts. Neither accepts a password.
"""

import argparse
import json
import os
import re
import sqlite3
import stat
import subprocess
import time
import uuid
from contextlib import closing
from pathlib import Path

SOURCE = "d4c1a8e37b62"
TARGET = "9f6c2a8d1b43"
FORMAT = 1
USER = ("id", "email", "role", "oauth", "scim")
AUTH = ("id", "email", "password", "active")
GROUP = ("id", "user_id", "name", "permissions")
MEMBER = ("id", "group_id", "user_id")
TABLES = {"user": USER, "auth": AUTH, "group": GROUP, "group_member": MEMBER}
NEW_PERMISSIONS = (
    ("chat", "side_chat"),
    ("workspace", "models_hidden"),
    ("features", "encrypted_channels"),
    ("features", "subagents"),
    ("features", "video_generation"),
)
PASSWORD = re.compile(
    r"(?:\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}|\$argon2(?:id|i|d)\$v=\d+\$m=\d+,t=\d+,p=\d+\$[A-Za-z0-9+/]+\$[A-Za-z0-9+/]+)"
)


class MigrationError(ValueError):
    pass


def open_db(path, mode):
    return sqlite3.connect(path.resolve(strict=True).as_uri() + "?mode=" + mode, uri=True, isolation_level=None)


def revision(db):
    return db.execute("SELECT version_num FROM alembic_version").fetchall()


def rows(db, table, columns):
    fields = ", ".join(f'"{name}"' for name in columns)
    return list(db.execute(f'SELECT {fields} FROM "{table}" ORDER BY id'))


def bindings(raw, field, seen):
    values = json.loads(raw) if raw else None
    if values is None:
        return None
    if not isinstance(values, dict):
        raise MigrationError("Invalid external identity collection")
    clean = {}
    for provider, binding in values.items():
        subject = binding.get(field) if isinstance(binding, dict) else None
        if field == "sub" and type(subject) is int:
            # Older OAuth rows can store the provider's numeric ID directly.
            subject = str(subject)
        if not provider or not isinstance(subject, str) or not subject.strip() or (provider, subject) in seen:
            raise MigrationError("Missing or duplicate external identity")
        seen.add((provider, subject))
        clean[provider] = {field: subject}
    return json.dumps(clean, sort_keys=True, separators=(",", ":")) if clean else None


def permissions(raw):
    value = json.loads(raw) if raw else None
    if value is None:
        return None

    def validate(tree):
        return isinstance(tree, dict) and all(
            isinstance(key, str) and (type(child) is bool or validate(child)) for key, child in tree.items()
        )

    if not validate(value):
        raise MigrationError("Permission data contains unsupported fields")
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def source_policy(defaults, stored):
    """Overlay the old persisted policy on effective defaults from the old service."""
    base = json.loads(permissions(defaults) or "{}")

    def apply(target, updates):
        for key, value in updates.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                apply(target[key], value)
            else:
                target[key] = value

    apply(base, json.loads(stored or "{}"))
    return permissions(json.dumps(base))


def candidate_policy(data):
    policy = json.loads(data["permissions"] or "{}")
    for raw in [policy, *(json.loads(row[3] or "{}") for row in data["group"])]:
        features = raw.get("features", {})
        if not isinstance(features, dict) or features.get("direct_tool_servers"):
            raise MigrationError("Source grants a retired or unrecognized feature permission")
        for section, key in NEW_PERMISSIONS:
            bucket = raw.get(section, {})
            if not isinstance(bucket, dict) or bucket.get(key):
                raise MigrationError("Source contains a grant unknown to its pinned schema")
    # The target enables subagents by default. Admission migration grants none
    # of the five features which did not exist on the pinned source.
    for section, key in NEW_PERMISSIONS:
        bucket = policy.setdefault(section, {})
        if not isinstance(bucket, dict):
            raise MigrationError("Invalid source permission section")
        bucket[key] = False
    return permissions(json.dumps(policy))


def read_admission(db):
    data = {name: rows(db, name, columns) for name, columns in TABLES.items()}
    accounts = {}
    oauth_seen, scim_seen, emails = set(), set(), set()
    people = []
    for ident, email, role, oauth, scim in data["user"]:
        if not ident or not isinstance(email, str) or not email.strip() or email.casefold() in emails:
            raise MigrationError("Missing or duplicate login identifier")
        if role not in {"admin", "user", "pending"}:
            raise MigrationError("Unrecognized admission role")
        emails.add(email.casefold())
        accounts[ident] = email
        people.append(
            (ident, email, role, bindings(oauth, "sub", oauth_seen), bindings(scim, "external_id", scim_seen))
        )
    data["user"] = people
    if not accounts or {row[0] for row in data["auth"]} != set(accounts):
        raise MigrationError("The user and authentication identities do not match")
    for ident, email, verifier, active in data["auth"]:
        if (
            email != accounts[ident]
            or active not in (0, 1)
            or not isinstance(verifier, str)
            or not PASSWORD.fullmatch(verifier)
        ):
            raise MigrationError("Login identifier, verifier or active state failed validation")
    active_ids = {row[0] for row in data["auth"] if row[3]}
    if not any(role == "admin" and ident in active_ids for ident, _, role, _, _ in people):
        raise MigrationError("Source has no active administrator")

    groups = {row[0] for row in data["group"]}
    if any(uid not in accounts or gid not in groups for _, gid, uid in data["group_member"]):
        raise MigrationError("Orphaned admission group membership")
    if len({(g, u) for _, g, u in data["group_member"]}) != len(data["group_member"]):
        raise MigrationError("Duplicate admission group membership")
    if any(owner not in accounts for _, owner, _, _ in data["group"]):
        raise MigrationError("Orphaned admission group owner")
    data["group"] = [(gid, owner, name, permissions(raw)) for gid, owner, name, raw in data["group"]]
    config = db.execute("SELECT value FROM config WHERE key='user.permissions'").fetchone()
    data["permissions"] = permissions(config[0]) if config else None
    return data


def insert(db, name, fields, records):
    columns = ",".join(f'"{key}"' for key in fields)
    marks = ",".join("?" for _ in fields)
    db.executemany(f'INSERT INTO "{name}" ({columns}) VALUES ({marks})', records)


def summary(data):
    return {
        "accounts": len(data["user"]),
        "disabled": sum(not row[3] for row in data["auth"]),
        "roles": {role: sum(r[2] == role for r in data["user"]) for role in ("admin", "user", "pending")},
        "external_bindings": sum(len(json.loads(raw)) for row in data["user"] for raw in row[3:] if raw),
        "groups": len(data["group"]),
        "memberships": len(data["group_member"]),
    }


def require_private_bundle(bundle):
    metadata = bundle.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise MigrationError("Login export must be a regular file with a single link")
    if os.name != "nt":
        if metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
            raise MigrationError("Login export must be owned by the operator and private")
        return
    # Ask Windows for SIDs, so localized account and permission names do not matter.
    check = """
$ErrorActionPreference = 'Stop'
$sid = [System.Security.Principal.SecurityIdentifier]
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$acl = Get-Acl -LiteralPath $env:WEBUI_CHECK_BUNDLE
if ($acl.GetOwner($sid).Value -ne $user) { exit 1 }
foreach ($rule in $acl.GetAccessRules($true, $true, $sid)) {
    if ($rule.AccessControlType -eq 'Allow' -and $rule.IdentityReference.Value -ne $user) { exit 1 }
}
"""
    checked = subprocess.run(
        ["pwsh.exe", "-NoProfile", "-NonInteractive", "-Command", check],
        env={**os.environ, "WEBUI_CHECK_BUNDLE": str(bundle.resolve())},
        capture_output=True,
    )
    if checked.returncode:
        raise MigrationError("Login export must be owned by the operator and private")


def export_login(source, bundle, source_defaults=None):
    with closing(open_db(source, "ro")) as db:
        db.execute("BEGIN")
        if revision(db) != [(SOURCE,)]:
            raise MigrationError("Unexpected source schema")
        data = read_admission(db)
        if source_defaults is not None:
            data["permissions"] = source_policy(source_defaults, data["permissions"])
        # Fail before writing when the target cannot preserve the source grants.
        candidate_policy(data)
    # Create the bundle before opening SQLite, so no verifier is written with
    # inherited/default file permissions. Reuse an interrupted empty export.
    if bundle.is_symlink() or (bundle.exists() and bundle.samefile(source)):
        raise MigrationError("Invalid login export destination")
    try:
        fd = os.open(bundle, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        created = False
    else:
        os.close(fd)
        created = True
    if os.name == "nt" and created:
        # The host account remains the only grantee. The directory must also
        # protect SQLite transaction files while an export is in progress.
        account = subprocess.check_output(["whoami"], text=True).strip()
        subprocess.run(
            ["icacls", str(bundle), "/inheritance:r", "/grant:r", account + ":F"], check=True, stdout=subprocess.DEVNULL
        )
    require_private_bundle(bundle)
    with closing(open_db(bundle, "rw")) as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM sqlite_schema LIMIT 1").fetchone():
            if db.execute("PRAGMA user_version").fetchone() == (FORMAT,) and read_admission(db) == data:
                return {**summary(data), "result": "ALREADY_EXPORTED"}
            raise MigrationError("Destination already contains different data")
        for name, fields in TABLES.items():
            columns = ", ".join(f'"{key}" ' + ("INTEGER" if key == "active" else "TEXT") for key in fields)
            db.execute(f'CREATE TABLE "{name}" ({columns}, PRIMARY KEY(id))')
            insert(db, name, fields, data[name])
        db.execute("CREATE TABLE config(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
        if data["permissions"] is not None:
            db.execute("INSERT INTO config VALUES ('user.permissions',?)", (data["permissions"],))
        db.execute(f"PRAGMA user_version={FORMAT}")
        db.commit()
    return {**summary(data), "result": "EXPORTED"}


def import_login(bundle, target):
    require_private_bundle(bundle)
    if bundle.samefile(target):
        raise MigrationError("Bundle and destination must be different files")
    with closing(open_db(bundle, "ro")) as src:
        src.execute("BEGIN")
        if src.execute("PRAGMA user_version").fetchone() != (FORMAT,):
            raise MigrationError("Incomplete or unrecognized login export")
        data = read_admission(src)
        data["permissions"] = candidate_policy(data)
    with closing(open_db(target, "rw")) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("BEGIN IMMEDIATE")
        if revision(db) != [(TARGET,)]:
            raise MigrationError("Unexpected target schema")
        system_tables = {"alembic_version", "config", *TABLES}
        for (name,) in db.execute("SELECT name FROM sqlite_schema WHERE type='table'"):
            if name in system_tables or name.startswith("sqlite_"):
                continue
            quoted = '"' + name.replace('"', '""') + '"'
            if db.execute(f"SELECT 1 FROM {quoted} LIMIT 1").fetchone():
                raise MigrationError("Target already contains application data or credentials")
        if db.execute("SELECT 1 FROM config WHERE key != 'user.permissions' LIMIT 1").fetchone():
            raise MigrationError("Target already contains instance settings")
        if any(db.execute(f'SELECT 1 FROM "{name}" LIMIT 1').fetchone() for name in TABLES):
            if read_admission(db) != data:
                raise MigrationError("Target contains different admission data")
            return {**summary(data), "result": "ALREADY_IMPORTED"}
        current = db.execute("SELECT value FROM config WHERE key='user.permissions'").fetchone()
        if current and permissions(current[0]) != data["permissions"]:
            raise MigrationError("Target has conflicting admission permissions")
        now = int(time.time())
        insert(
            db,
            "user",
            USER + ("name", "last_active_at", "created_at", "updated_at"),
            [(*row, "User", now, now, now) for row in data["user"]],
        )
        insert(db, "auth", AUTH + ("session_stamp",), [(*row, str(uuid.uuid4())) for row in data["auth"]])
        insert(
            db,
            "group",
            GROUP + ("description", "created_at", "updated_at"),
            [(*row, "", now, now) for row in data["group"]],
        )
        insert(
            db,
            "group_member",
            MEMBER + ("created_at", "updated_at"),
            [(*row, now, now) for row in data["group_member"]],
        )
        if data["permissions"] is not None and current is None:
            db.execute(
                "INSERT INTO config(key,value,updated_at) VALUES ('user.permissions',?,?)", (data["permissions"], now)
            )
        if db.execute("PRAGMA foreign_key_check").fetchone() or read_admission(db) != data:
            raise MigrationError("Admission reconciliation failed")
        db.commit()
    return {**summary(data), "result": "IMPORTED"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    exporter = commands.add_parser("export")
    exporter.add_argument("--source", type=Path, required=True)
    exporter.add_argument("--bundle", type=Path, required=True)
    exporter.add_argument(
        "--source-defaults",
        type=Path,
        help="Old service's effective default permission JSON when customized through its environment",
    )
    importer = commands.add_parser("import")
    importer.add_argument("--bundle", type=Path, required=True)
    importer.add_argument("--target", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "export":
            defaults = args.source_defaults.read_text(encoding="utf-8") if args.source_defaults else None
            result = export_login(args.source, args.bundle, defaults)
        else:
            result = import_login(args.bundle, args.target)
    except MigrationError as exc:
        parser.exit(1, f"{exc}\n")
    except (OSError, ValueError, sqlite3.Error, subprocess.SubprocessError):
        parser.exit(1, "Login migration failed; check schema, file access and destination constraints.\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
