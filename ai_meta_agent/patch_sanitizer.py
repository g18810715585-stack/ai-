from __future__ import annotations

import re
from typing import Any

from .models import Patch


REWARD_SLOT_FIELD = re.compile(r"^(type|reward|num|weight)_(\d+)$")


def sanitize_patch(patch: Patch) -> dict[str, Any]:
    """Remove AI placeholder values that should not be written as real data."""
    return {
        "blank_insert_fields": sanitize_blank_insert_fields(patch),
        "reward_unused_slots": sanitize_reward_unused_slots(patch),
    }


def sanitize_blank_insert_fields(patch: Patch) -> dict[str, Any]:
    removed: list[dict[str, Any]] = []
    for operation_index, operation in enumerate(patch.operations):
        if operation.op not in {"insert", "replace_group"}:
            continue
        for row_index, row in enumerate(operation.rows):
            for field in list(row.keys()):
                value = row.get(field)
                if _is_blank(value):
                    removed.append(
                        {
                            "operation_index": operation_index,
                            "row_index": row_index,
                            "field": field,
                            "reason": "blank insert field omitted so the writer only writes concrete values",
                        }
                    )
                    row.pop(field, None)
    return {
        "removed_fields": len(removed),
        "items": removed,
    }


def sanitize_reward_unused_slots(patch: Patch) -> dict[str, Any]:
    removed: list[dict[str, Any]] = []
    for operation_index, operation in enumerate(patch.operations):
        if operation.target_table != "reward":
            continue
        for payload_name, row_index, row in _operation_rows(operation):
            for slot in _reward_slots(row):
                if slot < 2:
                    continue
                fields = sorted(
                    [field for field in row if _slot_number(field) == slot],
                    key=lambda field: ("type", "reward", "num", "weight").index(field.rsplit("_", 1)[0]),
                )
                if fields and all(_is_zeroish(row.get(field)) for field in fields):
                    values = {field: row.pop(field, None) for field in fields}
                    removed.append(
                        {
                            "operation_index": operation_index,
                            "payload": payload_name,
                            "row_index": row_index,
                            "slot": slot,
                            "fields": values,
                            "reason": "reward slot has only zero or blank placeholder values",
                        }
                    )
    return {
        "removed_field_groups": len(removed),
        "removed_fields": sum(len(item["fields"]) for item in removed),
        "items": removed,
    }


def _operation_rows(operation: Any) -> list[tuple[str, int | None, dict[str, Any]]]:
    if operation.op in {"insert", "replace_group"}:
        return [("rows", index, row) for index, row in enumerate(operation.rows)]
    if operation.op == "update":
        return [("set", None, operation.set)]
    return []


def _reward_slots(row: dict[str, Any]) -> list[int]:
    slots = {_slot_number(field) for field in row}
    return sorted(slot for slot in slots if slot is not None)


def _slot_number(field: str) -> int | None:
    match = REWARD_SLOT_FIELD.match(str(field))
    if not match:
        return None
    return int(match.group(2))


def _is_zeroish(value: Any) -> bool:
    if value in (None, ""):
        return True
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return value == 0
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return True
        try:
            return float(text) == 0
        except ValueError:
            return False
    return False


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())
