from __future__ import annotations

import re
from typing import Any

from .models import Patch

PLACEHOLDER_RE = re.compile(r"<NEW_[A-Z0-9_]+>")


def fill_incremental_placeholders(patch: Patch, context: dict[str, Any]) -> dict[str, Any]:
    """Fill or correct safe generated IDs from table profile baselines.

    AI may still use symbolic values such as ``<NEW_REWARD_ID_001>`` when it
    knows a row should be new but should not invent the concrete number. It may
    also guess a concrete number from the wrong part of a sheet. This helper
    only touches fields marked allocatable by table_profiles, mainly primary
    keys and group keys. Lookup/reference fields remain untouched.
    """
    profiles = context.get("target_table_profiles") or {}
    replacements: dict[str, Any] = {}
    token_replacements: dict[str, Any] = {}
    sequences: dict[tuple[str, str], int] = {}
    grouped_value_replacements: dict[tuple[str, str, str], int] = {}
    filled_fields: list[dict[str, Any]] = []
    corrected_fields: list[dict[str, Any]] = []
    skipped_fields: list[dict[str, Any]] = []

    for operation in patch.operations:
        if operation.op not in {"insert", "replace_group"}:
            continue
        profile = profiles.get(operation.target_table) or {}
        next_values = profile.get("next_values") or {}
        profile_fields = profile.get("fields") or {}
        allocatable_fields = _allocatable_fields(profile)
        if not next_values or not allocatable_fields:
            continue
        for row in operation.rows:
            for field, value in list(row.items()):
                is_placeholder = _is_new_placeholder(value)
                field_profile = profile_fields.get(field) or {}
                if not is_placeholder and not _should_correct_concrete_value(value, field_profile):
                    continue
                if field not in allocatable_fields:
                    skipped_fields.append({"table": operation.target_table, "field": field, "value": value, "reason": "field is not allocatable"})
                    continue
                sequence_key = (operation.target_table, str(field))
                group_key = (operation.target_table, str(field), str(value))
                if field_profile.get("allocation_role") == "group_key" and not is_placeholder and group_key in grouped_value_replacements:
                    row[field] = grouped_value_replacements[group_key]
                    continue
                current_value = sequences.get(sequence_key, _int_or_none(next_values.get(field)))
                if current_value is None:
                    skipped_fields.append({"table": operation.target_table, "field": field, "value": value, "reason": "missing numeric baseline"})
                    continue
                if is_placeholder:
                    placeholder = str(value)
                    if placeholder not in replacements:
                        replacements[placeholder] = current_value
                        sequences[sequence_key] = current_value + 1
                        filled_fields.append({"table": operation.target_table, "field": field, "placeholder": placeholder, "value": current_value})
                    row[field] = replacements[placeholder]
                    continue
                old_value = value
                if _same_scalar(old_value, current_value):
                    if field_profile.get("allocation_role") == "group_key":
                        grouped_value_replacements[group_key] = current_value
                    sequences[sequence_key] = current_value + 1
                    continue
                row[field] = current_value
                if field_profile.get("allocation_role") == "group_key":
                    grouped_value_replacements[group_key] = current_value
                sequences[sequence_key] = current_value + 1
                token_replacements[str(old_value)] = current_value
                corrected_fields.append({"table": operation.target_table, "field": field, "old_value": old_value, "value": current_value})

    if replacements or token_replacements:
        for operation in patch.operations:
            operation.match = _replace_tokens(_replace_placeholders(operation.match, replacements), token_replacements)
            operation.set = _replace_tokens(_replace_placeholders(operation.set, replacements), token_replacements)
            operation.rows = _replace_tokens(_replace_placeholders(operation.rows, replacements), token_replacements)
            operation.reason = _replace_tokens(_replace_text(operation.reason, replacements), token_replacements)
            operation.source_ref.workbook = _replace_tokens(_replace_text(operation.source_ref.workbook, replacements), token_replacements) if operation.source_ref.workbook else None
            operation.source_ref.sheet = _replace_tokens(_replace_text(operation.source_ref.sheet, replacements), token_replacements) if operation.source_ref.sheet else None
            operation.source_ref.field = _replace_tokens(_replace_text(operation.source_ref.field, replacements), token_replacements) if operation.source_ref.field else None
    return {"filled": replacements, "filled_fields": filled_fields, "corrected_fields": corrected_fields, "skipped_fields": skipped_fields}


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


def _should_correct_concrete_value(value: Any, field_profile: dict[str, Any]) -> bool:
    if _int_or_none(value) is None:
        return False
    if field_profile.get("next_value_basis") not in {"bottom_last_numeric", "activity_regular_section"}:
        return False
    # new_or_reuse IDs often have a domain-specific allocation rule, such as a
    # date prefix. Leave concrete AI values alone unless they are placeholders.
    if field_profile.get("allocation_role") == "primary_key" and field_profile.get("id_strategy") == "new_or_reuse":
        return False
    return field_profile.get("allocation_role") in {"primary_key", "group_key", "field_dictionary"}


def _replace_placeholders(value: Any, replacements: dict[str, Any]) -> Any:
    if isinstance(value, str):
        return _replace_text(value, replacements)
    if isinstance(value, list):
        return [_replace_placeholders(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: _replace_placeholders(item, replacements) for key, item in value.items()}
    return value


def _replace_tokens(value: Any, replacements: dict[str, Any]) -> Any:
    if not replacements:
        return value
    if isinstance(value, str):
        return _replace_token_text(value, replacements)
    if isinstance(value, list):
        return [_replace_tokens(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: _replace_tokens(item, replacements) for key, item in value.items()}
    return value


def _replace_token_text(value: str, replacements: dict[str, Any]) -> str:
    result = value
    for old, new in replacements.items():
        result = re.sub(rf"(?<!\d){re.escape(str(old))}(?!\d)", str(new), result)
    return result


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


def _same_scalar(left: Any, right: Any) -> bool:
    return str(left if left is not None else "").strip() == str(right if right is not None else "").strip()
