from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def make_run_dir(root: Path, label: str) -> Path:
    run_dir = root / f"{label}-{utc_stamp()}"
    counter = 1
    while run_dir.exists():
        run_dir = root / f"{label}-{utc_stamp()}-{counter}"
        counter += 1
    run_dir.mkdir(parents=True, exist_ok=False)
    latest = root / "latest"
    if latest.exists() or latest.is_symlink():
        if latest.is_dir() and not latest.is_symlink():
            # Leave real directories untouched. Windows symlink permissions vary,
            # so latest is represented by a text pointer instead.
            pass
    write_text(root / "LATEST_RUN.txt", str(run_dir.resolve()))
    return run_dir
