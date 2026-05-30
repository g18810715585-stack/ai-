from __future__ import annotations

from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from .models import ConfigTableRef, Manifest, SchemaBundle


EXCEL_SUFFIXES = {".xlsx", ".xlsm"}


def _resolve(base_dir: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def _iter_workbooks(root: Path, recursive: bool) -> list[Path]:
    if root.is_file() and root.suffix.lower() in EXCEL_SUFFIXES:
        return [root]
    if not root.exists() or not root.is_dir():
        return []
    pattern = "**/*" if recursive else "*"
    return sorted(path for path in root.glob(pattern) if path.is_file() and path.suffix.lower() in EXCEL_SUFFIXES and not path.name.startswith("~$"))


def discover_config_tables(manifest: Manifest, schema: SchemaBundle, base_dir: Path) -> tuple[Manifest, dict[str, Any]]:
    resolved = dict(manifest.config_tables)
    diagnostics: dict[str, Any] = {
        "roots": [],
        "matched": {},
        "unmatched_tables": [],
        "errors": [],
    }
    if not manifest.config_roots:
        diagnostics["unmatched_tables"] = [table for table in schema.tables if table not in resolved]
        return manifest, diagnostics

    workbook_cache: dict[Path, list[str]] = {}
    candidates: list[Path] = []
    for root in manifest.config_roots:
        root_path = _resolve(base_dir, root.path)
        workbooks = _iter_workbooks(root_path, root.recursive)
        diagnostics["roots"].append({"path": str(root_path), "recursive": root.recursive, "workbooks": len(workbooks)})
        candidates.extend(workbooks)

    for table_name, table in schema.tables.items():
        if table_name in resolved:
            diagnostics["matched"][table_name] = {
                "path": resolved[table_name].path,
                "sheet": resolved[table_name].sheet,
                "source": "manifest.config_tables",
            }
            continue
        expected_sheet = table.sheet or table_name
        expected_names = {table_name.lower(), expected_sheet.lower()}
        for workbook_path in candidates:
            try:
                if workbook_path not in workbook_cache:
                    workbook = load_workbook(workbook_path, read_only=True, data_only=True)
                    workbook_cache[workbook_path] = workbook.sheetnames
                    workbook.close()
                sheetnames = workbook_cache[workbook_path]
            except Exception as exc:  # noqa: BLE001 - report bad workbook, keep scanning others.
                diagnostics["errors"].append({"path": str(workbook_path), "message": str(exc)})
                continue
            matched_sheet = next((sheet for sheet in sheetnames if sheet.lower() in expected_names), None)
            if matched_sheet:
                resolved[table_name] = ConfigTableRef(path=str(workbook_path), sheet=matched_sheet)
                diagnostics["matched"][table_name] = {"path": str(workbook_path), "sheet": matched_sheet, "source": "sheet_name"}
                break
            if workbook_path.stem.lower() in expected_names and sheetnames:
                resolved[table_name] = ConfigTableRef(path=str(workbook_path), sheet=expected_sheet if expected_sheet in sheetnames else sheetnames[0])
                diagnostics["matched"][table_name] = {
                    "path": str(workbook_path),
                    "sheet": resolved[table_name].sheet,
                    "source": "file_name",
                }
                break
        if table_name not in resolved:
            diagnostics["unmatched_tables"].append(table_name)

    manifest.config_tables = resolved
    return manifest, diagnostics
