from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"BASEAI_API_KEY\s*=\s*[^ \n\r]+"),
]
SKIP_DIRS = {".git", ".runs", ".knowledge", "__pycache__", "node_modules"}


def iter_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.is_file() and path.suffix.lower() not in {".xlsx", ".xlsm", ".png", ".jpg", ".jpeg"}:
            files.append(path)
    return files


def main() -> int:
    findings = []
    for path in iter_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in SECRET_PATTERNS:
            if pattern.search(text) and path.name != ".env.example":
                findings.append(str(path.relative_to(ROOT)))
    if findings:
        print("Potential secrets found:")
        for finding in findings:
            print(f"- {finding}")
        return 1
    print("No obvious secrets found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
