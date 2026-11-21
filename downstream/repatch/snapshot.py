"""Back up the committed fork delta and verify it against its frozen upstream."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
KIT = ROOT / "downstream/repatch"
ICONS = ROOT / "downstream/branding/assets"
ADMIN = {".gitattributes", ".gitignore", "AGENTS.md", "README.md"}


def git(*args, env=None):
    return subprocess.check_output(["git", "--literal-pathspecs", *args], cwd=ROOT, env=env)


def commit(ref):
    return git("rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}").decode().strip()


def blob(ref, path):
    return git("cat-file", "blob", f"{ref}:{path}")


def safe_path(name):
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name or str(path) != name:
        raise ValueError(f"Invalid inventory path: {name}")
    return name


def product_snapshot(ref):
    config = json.loads(blob(ref, "downstream/adapter.json"))
    upstream = commit(config["upstream"]["commit"])
    git("merge-base", "--is-ancestor", upstream, ref)
    branding = json.loads(blob(ref, safe_path(config["branding_manifest"])))
    if branding["branding_id"] != config["branding_id"]:
        raise ValueError("Adapter and artwork identities differ")

    outputs = {}
    static = ["static/favicon.png"]
    for name, spec in branding["assets"].items():
        if PurePosixPath(safe_path(name)).name != name:
            raise ValueError(f"Expected an icon filename: {name}")
        path = f"static/static/{name}"
        data = blob(ref, path)
        if len(data) != spec["bytes"] or hashlib.sha256(data).hexdigest() != spec["sha256"]:
            raise ValueError(f"Unreviewed artwork at {path}")
        outputs[ICONS / name] = data
        static.append(path)
    if blob(ref, "static/favicon.png") != outputs[ICONS / "favicon.png"]:
        raise ValueError("The root favicon differs from the branded favicon")

    patched = [safe_path(path) for path in config["patched_paths"]]
    overlays = [safe_path(path) for path in config["overlay_paths"]]
    paths = sorted(patched + overlays + static)
    if len(set(paths)) != len(paths):
        raise ValueError("Duplicate protection path")
    statuses = git("diff", "--name-status", "--no-renames", "-z", upstream, ref).decode().split("\0")[:-1]
    actual = {path: status for status, path in zip(statuses[::2], statuses[1::2])
              if path not in ADMIN and not path.startswith(("docs/", "downstream/"))}
    expected = {path: "M" for path in patched}
    expected.update(dict.fromkeys(overlays, "A"))
    # An upstream version may add or remove an icon at its public path.
    for path in static:
        if path in actual:
            expected[path] = actual[path] if actual[path] in {"M", "A"} else "M"
    if actual != expected:
        mismatches = sorted(path for path in actual.keys() | expected.keys() if actual.get(path) != expected.get(path))
        raise ValueError("Review unclassified, moved or upstream-equivalent paths: " + ", ".join(mismatches))

    patch = git("diff", "--full-index", "--binary", "--no-color", "--no-ext-diff", "--no-textconv",
                "--no-renames", "--no-indent-heuristic", "--diff-algorithm=myers", "--unified=3",
                "--src-prefix=a/", "--dst-prefix=b/", "-O", os.devnull, upstream, ref, "--", *paths)
    outputs[KIT / "webui.patch"] = patch
    return upstream, paths, outputs


def replay(upstream, ref, paths, patch, index):
    # Keep the ordinary worktree/index out of the rehearsal.
    if index.is_symlink():
        raise ValueError("The rehearsal index cannot be a link")
    index = index.resolve()
    scratch = (ROOT / "temp").resolve()
    if not scratch.is_relative_to(ROOT) or not index.is_relative_to(scratch) or index == scratch or index.exists():
        raise ValueError("Choose a new rehearsal index under this checkout's temp directory")
    index.parent.mkdir(parents=True, exist_ok=True)
    objects = index.with_name(index.name + ".objects")
    objects.mkdir()
    original = git("rev-parse", "--path-format=absolute", "--git-path", "objects").decode().strip()
    alternates = os.pathsep.join(filter(None, (original, os.environ.get("GIT_ALTERNATE_OBJECT_DIRECTORIES"))))
    env = dict(os.environ, GIT_INDEX_FILE=str(index), GIT_OBJECT_DIRECTORY=str(objects),
               GIT_ALTERNATE_OBJECT_DIRECTORIES=alternates)
    git("read-tree", upstream, env=env)
    applied = subprocess.run(["git", "apply", "--cached", "--3way", "--whitespace=nowarn", str(patch)],
                             cwd=ROOT, env=env, capture_output=True)
    if applied.returncode:
        raise SystemExit(applied.stderr.decode(errors="replace"))
    git("diff", "--cached", "--quiet", ref, "--", *paths, env=env)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("refresh", "check"))
    parser.add_argument("--ref", default="HEAD", help="committed fork product to compare with its own adapter manifest")
    parser.add_argument("--replay-index", type=Path, help="also apply the backup to its pinned base in a new temporary Git index")
    args = parser.parse_args()
    ref = commit(args.ref)
    upstream, paths, outputs = product_snapshot(ref)
    git("diff", "--quiet", "HEAD", "--", *paths, "downstream/adapter.json", "downstream/branding/manifest.json")
    if args.action == "refresh":
        git("diff", "--quiet", ref, "HEAD", "--", *paths, "downstream/adapter.json", "downstream/branding/manifest.json")
    stale = sorted(path.name for path in ICONS.glob("*") if path not in outputs)
    if stale:
        raise ValueError("Review obsolete artwork in the backup: " + ", ".join(stale))
    drift = [path for path, data in outputs.items() if not path.is_file() or path.read_bytes() != data]
    if args.action == "check" and drift:
        raise SystemExit("Backup differs: " + ", ".join(str(p.relative_to(ROOT)) for p in drift))
    for path in drift:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(outputs[path])
    if args.replay_index:
        replay(upstream, ref, paths, KIT / "webui.patch", args.replay_index)
    print(f"{args.action}: {len(paths)} product paths, {len(outputs) - 1} icon assets, upstream {upstream[:12]}")
    if args.replay_index:
        print("Replayed Git modes and blob identities match the committed product.")


if __name__ == "__main__":
    main()
