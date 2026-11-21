"""Verify the private theme and Function sources without copying their contents to the fork."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


def write_private_archive(target, repository, sources):
    private_temp = repository / "temp"
    target = target.absolute()
    if (private_temp.resolve() != private_temp or target.resolve() != target
            or not target.is_relative_to(private_temp) or target == private_temp or target.suffix.lower() != ".zip"):
        raise ValueError("Choose a new .zip under the private source repository's temp directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=target.parent) as scratch:
        staged = Path(scratch) / "reviewed.zip"
        with ZipFile(staged, "x") as archive:
            for name, data in sorted(sources.items()):
                archive.writestr(ZipInfo(name), data, compress_type=ZIP_DEFLATED)
        with ZipFile(staged) as archive:
            if set(archive.namelist()) != sources.keys() or any(archive.read(n) != d for n, d in sources.items()):
                raise ValueError("The staged archive differs from the verified publication bytes")
        # Publish the complete file atomically. A concurrent export cannot replace it.
        os.link(staged, target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--theme-dir", type=Path, required=True)
    parser.add_argument("--functions-dir", type=Path, required=True)
    parser.add_argument("--private-archive", type=Path, help="also export reviewed bytes to a new ZIP in the private repository's temp directory")
    args = parser.parse_args()
    manifest = json.loads(Path(__file__).with_name("protected-sources.json").read_bytes())
    rev = manifest["commit"]
    sources = {}
    repositories = set()
    for group, directory in (("theme", args.theme_dir), ("functions", args.functions_dir)):
        prefix = subprocess.check_output(["git", "rev-parse", "--show-prefix"], cwd=directory).decode().strip()
        top = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], cwd=directory).decode().strip()
        repositories.add(Path(top).resolve())
        for name, expected in manifest[group].items():
            data = subprocess.check_output(["git", "cat-file", "blob", f"{rev}:{prefix}{name}"], cwd=directory)
            if f"{group}/{name}" in manifest["published_crlf"]:
                data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            if hashlib.sha256(data).hexdigest() != expected:
                raise SystemExit(f"Content hash mismatch: {group}/{name}")
            sources[f"{group}/{name}"] = data
    if len(repositories) != 1:
        raise ValueError("Select both directories from the same private repository")
    if args.private_archive:
        write_private_archive(args.private_archive, repositories.pop(), sources)
    print(f"Verified {len(sources)} protected sources at {rev[:12]}")


if __name__ == "__main__":
    main()
