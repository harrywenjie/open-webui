"""Verify the private theme and Function sources without copying their contents to the fork."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--theme-dir", type=Path, required=True)
    parser.add_argument("--functions-dir", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(Path(__file__).with_name("protected-sources.json").read_bytes())
    rev = manifest["commit"]
    count = 0
    for group, directory in (("theme", args.theme_dir), ("functions", args.functions_dir)):
        prefix = subprocess.check_output(["git", "rev-parse", "--show-prefix"], cwd=directory).decode().strip()
        for name, expected in manifest[group].items():
            data = subprocess.check_output(["git", "cat-file", "blob", f"{rev}:{prefix}{name}"], cwd=directory)
            if f"{group}/{name}" in manifest["published_crlf"]:
                data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            if hashlib.sha256(data).hexdigest() != expected:
                raise SystemExit(f"Content hash mismatch: {group}/{name}")
            count += 1
    print(f"Verified {count} protected sources at {rev[:12]}")


if __name__ == "__main__":
    main()
