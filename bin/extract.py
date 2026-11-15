#!/usr/bin/env python3
"""Validate and prepare extraction target directories."""

import shutil
import sys
from pathlib import Path


def which(program: str) -> str | None:
    return shutil.which(program)


def make_sure_path_exists(path: Path | str) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("only 2 arguments taken", file=sys.stderr)
        sys.exit(1)

    if not Path(sys.argv[1]).is_file():
        print("file doesn't exist", file=sys.stderr)
        sys.exit(1)

    try:
        make_sure_path_exists(sys.argv[2])
    except OSError as e:
        print(e, file=sys.stderr)
        sys.exit(1)

    print("cool, passed!")
