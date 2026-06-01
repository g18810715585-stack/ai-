from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any


VALUE_SOURCE_KEYWORDS = ("item_base", "value", "价值")
PLANNING_ROW_KEYWORDS = (
    "活动",
    "商品",
    "道具",
    "奖励",
    "价格",
    "限购",
    "数量",
    "时间",
    "开始",
    "结束",
    "组",
    "分组",
    "id",
    "ID",
    "type",
    "key",
    "form",
    "list",
)
PROFILE_FIELD_KEYS = (
    "field",
    "type",
    "required",
    "roles",
    "allocation_role",
    "id_strategy",
    "reference_table",
    "reference_field",
    "next_value",
    "next_value_basis",
    "bottom_last_value",
    "bottom_last_value_row",
    "activity_regular_last_numeric",
    "activity_regular_last_numeric_row",
    "enum_values",
    "sample_values",
    "top_values",
)


def optimize_context_for_ai(context: dict[str, Any]) -> dict[str, Any]:
    """Return the compact payload used for the model request.

    The caller keeps the original context for deterministic post-processing.
    This copy removes full value-table rows and reduces table profiles to the
    fields the model actually needs to reason about IDs, enums, and style.
    """
    optimized = deepcopy(context)
    optimized["workbooks"] = _compact_workbooks_for_ai(context.get("workbooks") or [])
    optimized["planning_evidence"] = _build_planning_evidence(context.get("workbooks") or [])
    optimized["value_table_summary"] = _value_table_summary(context)
    optimized["resolved_items"] = _resolved_items(context)
    optimized["unresolved_item_candidates"] = _unresolved_item_candidates(context)
    if "target_table_profiles" in optimized:
        optimized["target_table_profiles"] = compact_target_table_profiles(context.get("target_table_profiles") or {})
    optimized["context_optimization"] = {
        "mode": "deterministic_local_index_first",
        "notes": [
            "价值表全量行只保存在本地 analysis.json，不直接发送给 AI。",
            "AI 只接收本地命中的商品、待确认候选、精简规划证据和精简原表画像。",
            "确定性 ID 修正继续使用本地完整 target_table_profiles。",
        ],
    }
    return optimized


def compact_target_table_profiles(profiles: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for table_name, profile in profiles.items():
        if not isinstance(profile, dict):
            continue
        fields = {}
        for field, stat in (profile.get("fields") or {}).items():
            if not isinstance(stat, dict) or not _keep_profile_field(field, stat, profile):
                continue
            fields[field] = _compact_profile_field(stat)
        tail_rows = [_compact_tail_row(row, fields) for row in (profile.get("tail_rows") or [])[-5:]]
        compact[table_name] = {
            "sheet": profile.get("sheet"),
            "header_row": profile.get("header_row"),
            "row_count": profile.get("row_count"),
            "primary_key": profile.get("primary_key") or [],
            "group_key": profile.get("group_key"),
            "generation_summary": profile.get("generation_summary") or {},
            "next_values": profile.get("next_values") or {},
            "fields": fields,
            "tail_rows": [row for row in tail_rows if len(row) > 1],
        }
        if profile.get("error"):
            compact[table_name]["error"] = profile.get("error")
    return compact


def build_context_budget(original: dict[str, Any], optimized: dict[str, Any]) -> dict[str, Any]:
    original_bytes = _json_bytes(original)
    optimized_bytes = _json_bytes(optimized)
    value_before = _sample_row_total(original.get("workbooks") or [], value_only=True)
    value_after = _sample_row_total(optimized.get("workbooks") or [], value_only=True)
    planning_after = _planning_evidence_row_total(optimized.get("planning_evidence") or [])
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "deterministic_local_index_first",
        "original": {
            "bytes": original_bytes,
            "kb": round(original_bytes / 1024, 1),
            "estimated_tokens": _estimate_tokens(original_bytes),
            "top_level": _top_level_sizes(original),
        },
        "optimized": {
            "bytes": optimized_bytes,
            "kb": round(optimized_bytes / 1024, 1),
            "estimated_tokens": _estimate_tokens(optimized_bytes),
            "top_level": _top_level_sizes(optimized),
        },
        "savings": {
            "bytes": max(0, original_bytes - optimized_bytes),
            "kb": round(max(0, original_bytes - optimized_bytes) / 1024, 1),
            "estimated_tokens": max(0, _estimate_tokens(original_bytes) - _estimate_tokens(optimized_bytes)),
            "percent": round((1 - optimized_bytes / original_bytes) * 100, 1) if original_bytes else 0,
        },
        "rows": {
            "value_sample_rows_before": value_before,
            "value_sample_rows_sent_to_ai": value_after,
            "planning_evidence_rows_sent_to_ai": planning_after,
        },
        "item_resolution": (optimized.get("planning_item_resolution") or {}).get("summary") or {},
    }


def _compact_workbooks_for_ai(workbooks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for workbook in workbooks:
        is_value = _is_value_workbook(workbook)
        sheets = []
        for sheet in workbook.get("sheets") or []:
            sample_rows = [] if is_value else _compact_planning_rows(sheet.get("sample_rows") or [], limit=200)
            sheets.append(
                {
                    "name": sheet.get("name"),
                    "max_row": sheet.get("max_row"),
                    "max_column": sheet.get("max_column"),
                    "header_row": sheet.get("header_row"),
                    "headers": (sheet.get("headers") or [])[:80],
                    "sample_row_count": sheet.get("sample_row_count"),
                    "sample_rows_omitted": max(0, (sheet.get("sample_row_count") or 0) - len(sample_rows)),
                    "sample_rows": sample_rows,
                    "context_note": "价值表已转为本地索引，AI 不接收全量行。" if is_value else "规划表只保留与配表相关的非空字段。",
                }
            )
        result.append(
            {
                "source_id": workbook.get("source_id"),
                "source_type": workbook.get("source_type"),
                "path": workbook.get("path"),
                "url": workbook.get("url"),
                "role_hint": "item_base" if is_value else "planning",
                "sheets": sheets,
            }
        )
    return result


def _build_planning_evidence(workbooks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    evidence = []
    for workbook in workbooks:
        if _is_value_workbook(workbook):
            continue
        for sheet in workbook.get("sheets") or []:
            rows = _compact_planning_rows(sheet.get("sample_rows") or [], limit=200)
            evidence.append(
                {
                    "source_id": workbook.get("source_id"),
                    "sheet": sheet.get("name"),
                    "header_row": sheet.get("header_row"),
                    "rows": rows,
                    "row_count": len(rows),
                }
            )
    return evidence


def _compact_planning_rows(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    compact_rows = []
    for row in rows:
        compact = {"__row": row.get("__row")}
        for key, value in row.items():
            if key == "__row" or value in (None, ""):
                continue
            label = str(key)
            text = str(value)
            if _is_relevant_planning_field(label, text):
                compact[label] = _truncate(value, 220)
        if len(compact) > 1:
            compact_rows.append(compact)
        if len(compact_rows) >= limit:
            break
    return compact_rows


def _value_table_summary(context: dict[str, Any]) -> dict[str, Any]:
    resolution = context.get("planning_item_resolution") or {}
    sheets = []
    for workbook in context.get("workbooks") or []:
        if not _is_value_workbook(workbook):
            continue
        for sheet in workbook.get("sheets") or []:
            sheets.append(
                {
                    "source_id": workbook.get("source_id"),
                    "sheet": sheet.get("name"),
                    "sample_row_count": sheet.get("sample_row_count"),
                    "headers": (sheet.get("headers") or [])[:30],
                }
            )
    return {
        "enabled": resolution.get("enabled", False),
        "summary": resolution.get("summary") or {},
        "column_mappings": (resolution.get("column_mappings") or [])[:12],
        "warnings": resolution.get("warnings") or [],
        "sheets": sheets,
    }


def _resolved_items(context: dict[str, Any]) -> list[dict[str, Any]]:
    resolution = context.get("planning_item_resolution") or {}
    return (resolution.get("matches") or [])[:120]


def _unresolved_item_candidates(context: dict[str, Any]) -> list[dict[str, Any]]:
    resolution = context.get("planning_item_resolution") or {}
    result = []
    for item in (resolution.get("missing") or [])[:80]:
        result.append(
            {
                "product_name": item.get("product_name"),
                "planning_ref": item.get("planning_ref"),
                "reason": item.get("reason"),
                "candidates": (item.get("candidates") or [])[:5],
            }
        )
    return result


def _keep_profile_field(field: str, stat: dict[str, Any], profile: dict[str, Any]) -> bool:
    if field in (profile.get("primary_key") or []) or field == profile.get("group_key"):
        return True
    if stat.get("allocation_role") or stat.get("id_strategy") in {"new", "new_or_reuse"}:
        return True
    if stat.get("enum_values"):
        return True
    roles = stat.get("roles") or []
    if "lookup_ref" in roles or "foreign_key_candidate" in roles:
        return True
    return bool(stat.get("reference_table"))


def _compact_profile_field(stat: dict[str, Any]) -> dict[str, Any]:
    compact = {key: stat.get(key) for key in PROFILE_FIELD_KEYS if key in stat and stat.get(key) not in (None, "", [])}
    if "sample_values" in compact:
        compact["sample_values"] = compact["sample_values"][:5]
    if "top_values" in compact:
        compact["top_values"] = compact["top_values"][:5]
    if "enum_values" in compact:
        compact["enum_values"] = compact["enum_values"][:12]
    return compact


def _compact_tail_row(row: dict[str, Any], fields: dict[str, Any]) -> dict[str, Any]:
    keep = set(fields.keys())
    compact = {"__row": row.get("__row")}
    for key, value in row.items():
        if key == "__row" or key not in keep or value in (None, ""):
            continue
        compact[key] = _truncate(value, 160)
    return compact


def _is_value_workbook(workbook: dict[str, Any]) -> bool:
    text = " ".join(str(workbook.get(key) or "").lower() for key in ["source_id", "path", "url", "role_hint"])
    return any(keyword in text for keyword in VALUE_SOURCE_KEYWORDS)


def _is_relevant_planning_field(label: str, value: str) -> bool:
    text = f"{label} {value}"
    if any(keyword in text for keyword in PLANNING_ROW_KEYWORDS):
        return True
    return bool(value.strip()) and len(value.strip()) <= 80 and any(char.isdigit() for char in value)


def _truncate(value: Any, limit: int) -> Any:
    if isinstance(value, str) and len(value) > limit:
        return f"{value[:limit]}..."
    return value


def _sample_row_total(workbooks: list[dict[str, Any]], value_only: bool) -> int:
    total = 0
    for workbook in workbooks:
        if value_only and not _is_value_workbook(workbook):
            continue
        for sheet in workbook.get("sheets") or []:
            total += len(sheet.get("sample_rows") or [])
    return total


def _planning_evidence_row_total(items: list[dict[str, Any]]) -> int:
    return sum(len(item.get("rows") or []) for item in items)


def _json_bytes(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, default=str).encode("utf-8"))


def _top_level_sizes(value: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for key, item in value.items():
        size = _json_bytes(item)
        rows.append({"key": key, "kb": round(size / 1024, 1), "estimated_tokens": _estimate_tokens(size)})
    return sorted(rows, key=lambda item: item["kb"], reverse=True)


def _estimate_tokens(byte_count: int) -> int:
    return max(1, round(byte_count / 4))
