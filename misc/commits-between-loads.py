#!/usr/bin/env python3
"""List commits (with author and files) between two solcbr main loads."""

import argparse
import re
import subprocess
import sys
from pathlib import Path

LOADS_DIR = Path("/home/public/RND/loads/solcbr/main")


def get_sha(load: str) -> str:
    log = LOADS_DIR / load / "logs" / "build.log"
    if not log.exists():
        sys.exit(f"Error: build log not found: {log}")
    match = re.search(r"GIT_COMMIT=([0-9a-f]+)", log.read_text())
    if not match:
        sys.exit(f"Error: GIT_COMMIT not found in {log}")
    return match.group(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("older_load", help="e.g. 100.0main.0.6011")
    parser.add_argument("newer_load", help="e.g. 100.0main.0.6337")
    args = parser.parse_args()

    older_sha = get_sha(args.older_load)
    newer_sha = get_sha(args.newer_load)

    print(
        f"# Commits between {args.older_load} ({older_sha}) and {args.newer_load} ({newer_sha})\n"
    )

    result = subprocess.run(
        [
            "git",
            "log",
            f"{older_sha}..{newer_sha}",
            "--format=commit %H\nAuthor: %an\n%s",
            "--name-only",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    print(result.stdout)


if __name__ == "__main__":
    main()
