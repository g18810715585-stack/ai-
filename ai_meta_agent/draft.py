from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timezone
from typing import Any

from openpyxl import load_workbook

from .models import Manifest, Patch, PatchOperation, SchemaBundle, SourceRef


def _coerce(value: Any, field_type: str) -> Any:
    if value in (None, ""):
        return None
    if field_type == "int":
        try:
            return int(value)
        except (TypeError, ValueError):
            return value
    if field_type == "float":
        try:
            return float(value)
        except (TypeError, ValueError):
            return value
    if field_type == "str":
        return str(value)
    return value


def _existing_keys(path: str, sheet_name: str | None, primary_key: list[str]) -> set[tuple[Any, ...]]:
    if not path or not primary_key:
        return set()
    workbook = load_workbook(path, data_only=True)
    sheet = workbook[sheet_name] if sheet_name and sheet_name in workbook.sheetnames else workbook.active
    headers = [sheet.cell(1, col).value for col in range(1, sheet.max_column + 1)]
    indexes = {str(header): idx + 1 for idx, header in enumerate(headers) if header}
    keys: set[tuple[Any, ...]] = set()
    for row_idx in range(2, sheet.max_row + 1):
        key = tuple(sheet.cell(row_idx, indexes[field]).value for field in primary_key if field in indexes)
        if len(key) == len(primary_key) and any(item is not None for item in key):
            keys.add(key)
    return keys


def make_stub_patch(manifest: Manifest, schema: SchemaBundle, context: dict[str, Any], base_dir: str) -> Patch:
    operations: list[PatchOperation] = []
    patch_id = datetime.now(timezone.utc).strftime("patch_%Y%m%d_%H%M%S")
    config_keys: dict[str, set[tuple[Any, ...]]] = {}
    for table_name, table in schema.tables.items():
        ref = manifest.config_tables.get(table_name)
        if ref:
            path = ref.path
            if not os.path.isabs(path):
                path = os.path.abspath(os.path.join(base_dir, path))
            config_keys[table_name] = _existing_keys(path, ref.sheet or table.sheet, table.primary_key)
        else:
            config_keys[table_name] = set()

    for workbook in context.get("workbooks", []):
        for sheet in workbook.get("sheets", []):
            headers = sheet.get("headers") or []
            header_to_table_field: dict[str, tuple[str, str]] = {}
            for table_name, table in schema.tables.items():
                for header in headers:
                    if header in table.field_aliases:
                        header_to_table_field[header] = (table_name, table.field_aliases[header])
                    elif header in table.fields:
                        header_to_table_field[header] = (table_name, header)
            for source_row in sheet.get("sample_rows", []):
                rows_by_table: dict[str, dict[str, Any]] = {}
                for header, value in source_row.items():
                    if header.startswith("__") or header not in header_to_table_field:
                        continue
                    table_name, field = header_to_table_field[header]
                    table = schema.tables[table_name]
                    spec = table.fields.get(field)
                    rows_by_table.setdefault(table_name, {})[field] = _coerce(value, spec.type if spec else "any")
                for table_name, row in rows_by_table.items():
                    table = schema.tables[table_name]
                    if not table.primary_key or not all(row.get(field) not in (None, "") for field in table.primary_key):
                        continue
                    for field, spec in table.fields.items():
                        if row.get(field) in (None, "") and spec.default is not None:
                            row[field] = spec.default
                    key = tuple(row.get(field) for field in table.primary_key)
                    exists = key in config_keys.get(table_name, set())
                    safe_set = {
                        field: value
                        for field, value in row.items()
                        if field not in table.block_update_fields and (not table.allow_update_fields or field in table.allow_update_fields)
                    }
                    confidence = 0.86 if exists else 0.82
                    if exists:
                        operations.append(
                            PatchOperation(
                                op="update",
                                target_table=table_name,
                                match={field: row[field] for field in table.primary_key},
                                set=safe_set,
                                source_ref=SourceRef(workbook=workbook.get("source_id"), sheet=sheet.get("name"), row=source_row.get("__row")),
                                reason="stub draft matched an existing primary key and generated a supervised field-level update",
                                confidence=confidence,
                                risk_level="medium",
                                needs_confirmation=True,
                            )
                        )
                    else:
                        operations.append(
                            PatchOperation(
                                op="insert",
                                target_table=table_name,
                                rows=[row],
                                source_ref=SourceRef(workbook=workbook.get("source_id"), sheet=sheet.get("name"), row=source_row.get("__row")),
                                reason="stub draft did not find the primary key in the target table and generated an insert",
                                confidence=confidence,
                                risk_level="medium",
                                needs_confirmation=True,
                            )
                        )
    return Patch(patch_id=patch_id, project=manifest.project, mode=manifest.mode, operations=operations)


def call_baseai(manifest: Manifest, context: dict[str, Any]) -> Patch:
    api_key = os.environ.get(manifest.ai.api_key_env)
    if not api_key:
        raise RuntimeError(f"Missing API key env var: {manifest.ai.api_key_env}. Use --stub for local dry runs.")
    base_url = os.environ.get(manifest.ai.base_url_env, manifest.ai.default_base_url).rstrip("/")
    model = os.environ.get(manifest.ai.model_env, manifest.ai.default_model)
    url = f"{base_url}/chat/completions"
    body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are an AI meta configuration agent. Return only strict JSON matching the Patch schema.",
            },
            {
                "role": "user",
                "content": json.dumps(context, ensure_ascii=False),
            },
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        payload = json.loads(response.read().decode("utf-8"))
    content = payload["choices"][0]["message"]["content"]
    return Patch.model_validate(json.loads(content))
