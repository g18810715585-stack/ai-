from __future__ import annotations

import re
from typing import Any

from .models import Patch

PLACEHOLDER_RE = re.compile(r"<NEW_[A-Z0-9_]+>")


def fill_incremental_placeholders(patch: Patch, context: dict[str, Any]) -> dict[str, Any]:
    """Fill safe generated placeholders from table profile baselines.

    AI may still use symbolic values such as ``<NEW_REWARD_ID_001>`` when it
    knows a row should be new but should not invent the concrete number. This
    helper only fills fields marked allocatable by table_profiles, mainly
    primary keys and group keys. Lookup/reference fields remain untouched.
    """
    profiles = context.get("target_table_profiles") or {}
    replacements: dict[str, Any] = {}
    sequences: dict[tuple[str, str], int] = {}
    filled_fields: list[dict[str, Any]] = []
    skipped_fields: list[dict[str, Any]] = []

    for operation in patch.operations:
        if operation.op not in {"insert", "replace_group"}:
            continue
        profile = profiles.get(operation.target_table) or {}
        next_values = profile.get("next_values") or {}
        allocatable_fields = _allocatable_fields(profile)
        if not next_values or not allocatable_fields:
            continue
        for row in operation.rows:
            for field, value in list(row.items()):
                if not _is_new_placeholder(value):
                    continue
                if field not in allocatable_fields:
                    skipped_fields.append({"table": operation.target_table, "field": field, "placeholder": value, "reason": "field is not allocatable"})
                    continue
                sequence_key = (operation.target_table, str(field))
                current_value = sequences.get(sequence_key, _int_or_none(next_values.get(field)))
                if current_value is None:
                    skipped_fields.append({"table": operation.target_table, "field": field, "placeholder": value, "reason": "missing numeric baseline"})
                    continue
                placeholder = str(value)
                if placeholder not in replacements:
                    replacements[placeholder] = current_value
                    sequences[sequence_key] = current_value + 1
                    filled_fields.append({"table": operation.target_table, "field": field, "placeholder": placeholder, "value": current_value})
                row[field] = replacements[placeholder]

    if replacements:
        for operation in patch.operations:
            operation.match = _replace_placeholders(operation.match, replacements)
            operation.set = _replace_placeholders(operation.set, replacements)
            operation.rows = _replace_placeholders(operation.rows, replacements)
            operation.reason = _replace_text(operation.reason, replacements)
            operation.source_ref.workbook = _replace_text(operation.source_ref.workbook, replacements) if operation.source_ref.workbook else None
            operation.source_ref.sheet = _replace_text(operation.source_ref.sheet, replacements) if operation.source_ref.sheet else None
            operation.source_ref.field = _replace_text(operation.source_ref.field, replacements) if operation.source_ref.field else None
    return {"filled": replacements, "filled_fields": filled_fields, "skipped_fields": skipped_fields}


def fill_active_shop_incremental_ids(patch: Patch, context: dict[str, Any]) -> dict[str, Any]:
    """Backward-compatible wrapper for older callers and tests."""
    return fill_incremental_placeholders(patch, context)


def _allocatable_fields(profile: dict[str, Any]) -> set[str]:
    fields = set((profile.get("generation_summary") or {}).get("allocatable_fields") or [])
    if fields:
        return fields
    # Compatibility for contexts produced before generation_summary existed.
    return {str(field) for field in (profile.get("next_values") or {})}


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
