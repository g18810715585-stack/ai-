from __future__ import annotations

import re
from typing import Any

from .models import Patch, SchemaBundle


REWARD_SLOT_FIELD = re.compile(r"^(type|reward|num|weight)_(\d+)$")


def sanitize_patch(patch: Patch) -> dict[str, Any]:
    """Remove AI placeholder values that should not be written as real data."""
    return {
        "blank_insert_fields": sanitize_blank_insert_fields(patch),
        "reward_unused_slots": sanitize_reward_unused_slots(patch),
    }


def apply_reward_top_level_defaults(patch: Patch, schema: SchemaBundle, context: dict[str, Any]) -> dict[str, Any]:
    """Fill deterministic reward defaults learned from exchange-shop corrections.

    The user's exchange-shop rule is about the top-level reward.type/reward.num
    fields, not reward slot fields such as num_1. Keep this local and explicit
    so a compressed model context cannot accidentally drop the rule.
    """
    reward_schema = schema.tables.get("reward")
    if not reward_schema or not _is_exchange_shop_context(context):
        return {"applied": False, "filled_fields": 0, "items": []}
    available_fields = set(reward_schema.fields)
    if not ({"type", "num"} & available_fields):
        return {"applied": False, "filled_fields": 0, "items": []}

    items: list[dict[str, Any]] = []
    for operation_index, operation in enumerate(patch.operations):
        if operation.target_table != "reward" or operation.op not in {"insert", "replace_group", "update"}:
            continue
        for payload_name, row_index, row in _operation_rows(operation):
            changed: dict[str, dict[str, Any]] = {}
            if "type" in available_fields and _needs_reward_default(row.get("type"), expected=2):
                changed["type"] = {"before": row.get("type"), "after": 2}
                row["type"] = 2
            if "num" in available_fields and _needs_reward_default(row.get("num"), expected=1):
                changed["num"] = {"before": row.get("num"), "after": 1}
                row["num"] = 1
            if changed:
                items.append(
                    {
                        "operation_index": operation_index,
                        "payload": payload_name,
                        "row_index": row_index,
                        "fields": changed,
                        "reason": "exchange-shop reward correction requires top-level reward.type=2 and reward.num=1",
                    }
                )
    return {"applied": bool(items), "filled_fields": sum(len(item["fields"]) for item in items), "items": items}


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


def _needs_reward_default(value: Any, expected: int) -> bool:
    if value in (None, ""):
        return True
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return value == 0 or int(value) != expected
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return True
        try:
            return int(float(text)) != expected
        except ValueError:
            return False
    return False


def _is_exchange_shop_context(context: dict[str, Any]) -> bool:
    target_tables = {str(table) for table in context.get("target_tables") or []}
    if {"active_shop", "reward"}.issubset(target_tables):
        return True
    structured = context.get("structured_planning") or {}
    for source in structured.get("sources") or []:
        if source.get("shop_items") or source.get("shop_groups"):
            return True
    text_parts: list[str] = []
    plan = context.get("config_plan") or {}
    text_parts.extend(
        str(plan.get(key) or "")
        for key in ["activity_type", "run_instruction", "template_rule"]
    )
    for item in context.get("structured_corrections") or []:
        text_parts.append(str(item.get("correct_practice") or ""))
        text_parts.append(str(item.get("error_pattern") or ""))
    text = "\n".join(text_parts)
    return any(marker in text for marker in ("兑换店", "兑换商店", "active_shop", "exchange shop"))


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
