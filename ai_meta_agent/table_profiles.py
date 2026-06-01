from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from .models import Manifest, SchemaBundle, resolve_path


def build_target_table_profiles(manifest: Manifest, schema: SchemaBundle, base_dir: Path) -> dict[str, Any]:
    profiles: dict[str, Any] = {}
    for table_name, table in schema.tables.items():
        ref = manifest.config_tables.get(table_name)
        if not ref:
            continue
        path = resolve_path(base_dir, ref.path)
        if not path.exists():
            continue
        try:
            profiles[table_name] = _profile_table(path, ref.sheet or table_name, table.primary_key, list(table.fields.keys()))
        except Exception as exc:  # noqa: BLE001 - profiles are advisory context only.
            profiles[table_name] = {"path": str(path), "sheet": ref.sheet or table_name, "error": str(exc)}
    return profiles


def _profile_table(path: Path, sheet_name: str, primary_key: list[str], schema_fields: list[str]) -> dict[str, Any]:
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook[sheet_name] if sheet_name in workbook.sheetnames else workbook.active
        header_row, headers = _detect_header(sheet, schema_fields)
        if not header_row:
            return {"path": str(path), "sheet": sheet.title, "error": "未识别到表头"}
        header_to_index = {header: index for index, header in enumerate(headers) if header}
        profile_fields = _profile_fields(primary_key, schema_fields)
        field_stats = {field: _empty_field_stat() for field in profile_fields if field in header_to_index}
        tail_rows: deque[dict[str, Any]] = deque(maxlen=12)
        row_count = 0
        for row_index, raw in enumerate(sheet.iter_rows(min_row=header_row + 1, values_only=True), start=header_row + 1):
            if not any(value not in (None, "") for value in raw):
                continue
            row_count += 1
            compact_row: dict[str, Any] = {"__row": row_index}
            for field, stat in field_stats.items():
                index = header_to_index[field]
                value = raw[index] if index < len(raw) else None
                if value in (None, ""):
                    continue
                compact_row[field] = value
                _update_field_stat(stat, value, row_index)
            if len(compact_row) > 1:
                tail_rows.append(compact_row)
        next_values = {
            field: stat["max_numeric"] + 1
            for field, stat in field_stats.items()
            if stat.get("max_numeric") is not None
        }
        return {
            "path": str(path),
            "sheet": sheet.title,
            "header_row": header_row,
            "row_count": row_count,
            "primary_key": primary_key,
            "profile_fields": list(field_stats.keys()),
            "fields": field_stats,
            "next_values": next_values,
            "tail_rows": list(tail_rows),
        }
    finally:
        workbook.close()


def _detect_header(sheet: Any, schema_fields: list[str]) -> tuple[int | None, list[str]]:
    schema_set = set(schema_fields)
    best_row: int | None = None
    best_values: list[str] = []
    best_score = 0
    for row_index, row in enumerate(sheet.iter_rows(min_row=1, max_row=min(sheet.max_row or 0, 30), values_only=True), start=1):
        values = ["" if value is None else str(value).strip() for value in row]
        non_empty = sum(1 for value in values if value)
        matches = sum(1 for value in values if value in schema_set)
        score = matches * 10 + non_empty
        if score > best_score:
            best_row = row_index
            best_values = values
            best_score = score
    if best_score < 2:
        return None, []
    return best_row, best_values


def _profile_fields(primary_key: list[str], schema_fields: list[str]) -> list[str]:
    fields: list[str] = []
    for field in [*primary_key, *schema_fields]:
        normalized = field.lower()
        if field in primary_key or "组" in field or normalized in {"group", "group_id"} or normalized.endswith("_group"):
            fields.append(field)
    return _ordered_unique(fields)


def _empty_field_stat() -> dict[str, Any]:
    return {
        "max_numeric": None,
        "max_numeric_row": None,
        "last_numeric": None,
        "last_numeric_row": None,
        "last_value": None,
        "last_value_row": None,
    }


def _update_field_stat(stat: dict[str, Any], value: Any, row_index: int) -> None:
    stat["last_value"] = value
    stat["last_value_row"] = row_index
    numeric = _numeric_value(value)
    if numeric is None:
        return
    stat["last_numeric"] = numeric
    stat["last_numeric_row"] = row_index
    if stat["max_numeric"] is None or numeric > stat["max_numeric"]:
        stat["max_numeric"] = numeric
        stat["max_numeric_row"] = row_index


def _numeric_value(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    return None


def _ordered_unique(values: list[str]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
