from __future__ import annotations

import re
from typing import Any

from .models import Patch

PLACEHOLDER_RE = re.compile(r"<NEW_[A-Z0-9_]+>")


def fill_active_shop_incremental_ids(patch: Patch, context: dict[str, Any]) -> dict[str, Any]:
    profile = (context.get("target_table_profiles") or {}).get("active_shop") or {}
    next_values = profile.get("next_values") or {}
    next_id = _int_or_none(next_values.get("id"))
    next_group = _int_or_none(next_values.get("商品组"))
    if next_id is None and next_group is None:
        return {"filled": {}, "reason": "active_shop profile has no numeric next values"}

    replacements: dict[str, Any] = {}
    for operation in patch.operations:
        if operation.target_table != "active_shop" or operation.op != "insert":
            continue
        for row in operation.rows:
            if next_id is not None and _is_new_placeholder(row.get("id")):
                replacements[str(row["id"])] = next_id
                row["id"] = next_id
                next_id += 1
            if next_group is not None and _is_new_placeholder(row.get("商品组")):
                placeholder = str(row["商品组"])
                if placeholder not in replacements:
                    replacements[placeholder] = next_group
                    next_group += 1
                row["商品组"] = replacements[placeholder]

    if replacements:
        for operation in patch.operations:
            operation.match = _replace_placeholders(operation.match, replacements)
            operation.set = _replace_placeholders(operation.set, replacements)
            operation.rows = _replace_placeholders(operation.rows, replacements)
            operation.reason = _replace_text(operation.reason, replacements)
            operation.source_ref.workbook = _replace_text(operation.source_ref.workbook, replacements)
            operation.source_ref.sheet = _replace_text(operation.source_ref.sheet, replacements) if operation.source_ref.sheet else None
            operation.source_ref.field = _replace_text(operation.source_ref.field, replacements) if operation.source_ref.field else None
    return {"filled": replacements}


def _is_new_placeholder(value: Any) -> bool:
    return isinstance(value, str) and bool(PLACEHOLDER_RE.fullmatch(value.strip()))


def _replace_placeholders(value: Any, replacements: dict[str, Any]) -> Any:
    if isinstance(value, str):
        return _replace_text(value, replacements)
    if isinstance(value, list):
        return [_replace_placeholders(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: _replace_placeholders(item, replacements) for key, item in value.items()}
    return value


def _replace_text(value: str, replacements: dict[str, Any]) -> Any:
    if value in replacements:
        return replacements[value]
    result = value
    for placeholder, replacement in replacements.items():
        result = result.replace(placeholder, str(replacement))
    return result


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    text = str(value).strip()
    return int(text) if text.isdigit() else None
