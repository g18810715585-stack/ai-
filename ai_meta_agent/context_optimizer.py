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
PROFILE_FIELD_LIMIT_AI = 18
PROFILE_TAIL_ROW_LIMIT_AI = 3
PROFILE_SAMPLE_VALUE_LIMIT_AI = 3
PROFILE_TOP_VALUE_LIMIT_AI = 3
PROFILE_ENUM_VALUE_LIMIT_AI = 8
PROFILE_PRIORITY_KEYWORDS = (
    "id",
    "ID",
    "group",
    "reward",
    "goods",
    "item",
    "key",
    "form",
    "list",
    "switch",
    "cost",
    "price",
    "time",
    "type",
    "shop",
    "活动",
    "商品",
    "奖励",
    "道具",
    "消耗",
    "价格",
    "限购",
    "时间",
    "类型",
    "组",
    "开关",
    "排序",
)
SCHEMA_RELATIONSHIP_CANDIDATE_LIMIT_AI = 30
RELATIONSHIP_LIMIT_AI = 28
PLAN_FIELD_MAPPING_LIMIT_AI = 12
PLAN_FIELD_DICTIONARY_LIMIT_AI = 16
PLAN_RULE_LIMIT_AI = 6
PLAN_CASE_LIMIT_AI = 3
PLAN_CORRECTION_LIMIT_AI = 5
KNOWLEDGE_STRING_LIMIT_AI = 320


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
    if "schema" in optimized:
        optimized["schema"] = compact_schema_for_ai(context.get("schema") or {})
    if "relationship_map" in optimized:
        optimized["relationship_map"] = compact_relationship_map_for_ai(context.get("relationship_map") or {})
    if "config_discovery" in optimized:
        optimized["config_discovery"] = compact_config_discovery_for_ai(context.get("config_discovery") or {})
    if "config_plan" in optimized:
        optimized["config_plan"] = compact_config_plan_for_ai(context.get("config_plan") or {})
    _compact_top_level_knowledge(optimized)
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


def compact_schema_for_ai(schema: dict[str, Any]) -> dict[str, Any]:
    tables: dict[str, Any] = {}
    for table_name, table in (schema.get("tables") or {}).items():
        if not isinstance(table, dict):
            continue
        fields = table.get("fields") or {}
        field_names = list(fields.keys()) if isinstance(fields, dict) else []
        required_fields: list[str] = []
        typed_fields: dict[str, str] = {}
        default_values: dict[str, Any] = {}
        if isinstance(fields, dict):
            for field, spec in fields.items():
                if not isinstance(spec, dict):
                    continue
                if spec.get("required"):
                    required_fields.append(field)
                field_type = spec.get("type")
                if field_type and field_type not in {"any", "str"}:
                    typed_fields[field] = field_type
                if spec.get("default") not in (None, "", []):
                    default_values[field] = spec.get("default")
        allow_update_fields = table.get("allow_update_fields") or []
        allow_update_set = set(allow_update_fields)
        field_name_set = set(field_names)
        compact = {
            "sheet": table.get("sheet"),
            "primary_key": table.get("primary_key") or [],
            "group_key": table.get("group_key"),
            "overwrite_strategy": table.get("overwrite_strategy"),
            "ai_write_permission": table.get("ai_write_permission"),
            "preserve_fields": table.get("preserve_fields") or [],
            "block_update_fields": table.get("block_update_fields") or [],
            "field_names": field_names,
        }
        if allow_update_fields and allow_update_set != field_name_set:
            compact["allow_update_fields"] = allow_update_fields
        elif allow_update_fields:
            compact["allow_update_policy"] = "all_field_names"
        aliases = table.get("field_aliases") or {}
        if aliases:
            compact["field_aliases"] = dict(list(aliases.items())[:40])
        if required_fields:
            compact["required_fields"] = required_fields
        if typed_fields:
            compact["field_types"] = typed_fields
        if default_values:
            compact["default_values"] = default_values
        tables[table_name] = {key: value for key, value in compact.items() if value not in (None, "", [], {})}
    return {
        "tables": tables,
        "risk": schema.get("risk") or {},
        "relationship_candidates": (schema.get("relationship_candidates") or [])[:SCHEMA_RELATIONSHIP_CANDIDATE_LIMIT_AI],
    }


def compact_relationship_map_for_ai(result: dict[str, Any]) -> dict[str, Any]:
    targets = set(result.get("target_tables") or [])
    recommended = set(result.get("recommended_tables") or [])
    relations = []
    raw_relations = list(result.get("relations") or [])
    raw_relations.sort(key=lambda item: (-_relationship_priority(item, targets, recommended), item.get("from_table") or "", item.get("from_field") or ""))
    for relation in raw_relations[:RELATIONSHIP_LIMIT_AI]:
        evidence = relation.get("evidence") or {}
        relations.append(
            {
                "from_table": relation.get("from_table"),
                "from_field": relation.get("from_field"),
                "to_table": relation.get("to_table"),
                "to_field": relation.get("to_field"),
                "relation_type": relation.get("relation_type"),
                "confidence": relation.get("confidence"),
                "risk": relation.get("risk"),
                "hop": relation.get("hop"),
                "evidence": {
                    "hit_rate": evidence.get("hit_rate"),
                    "hit_count": evidence.get("hit_count"),
                    "sample_values": (evidence.get("sample_values") or evidence.get("matched_values") or [])[:3],
                },
            }
        )
    compact = {
        "version": result.get("version"),
        "target_tables": result.get("target_tables") or [],
        "recommended_tables": result.get("recommended_tables") or [],
        "summary": result.get("summary") or {},
        "relations": relations,
    }
    omitted = max(0, len(raw_relations) - len(relations))
    if omitted:
        compact["omitted_relations"] = omitted
    ai_review = result.get("ai_review") or {}
    if ai_review:
        compact["ai_review"] = {
            "recommended_tables": (ai_review.get("recommended_tables") or [])[:12],
            "notes": [_truncate(item, 220) for item in (ai_review.get("notes") or [])[:6]],
            "risks": [_truncate(item, 220) for item in (ai_review.get("risks") or [])[:6]],
            "pending_confirmations": [_truncate(item, 220) for item in (ai_review.get("pending_confirmations") or [])[:8]],
        }
    return compact


def compact_config_discovery_for_ai(discovery: dict[str, Any]) -> dict[str, Any]:
    targets = discovery.get("target_tables") or discovery.get("targets") or []
    found = discovery.get("found_tables") or discovery.get("configured_tables") or discovery.get("tables") or {}
    if isinstance(found, dict):
        found_names = list(found.keys())
    elif isinstance(found, list):
        found_names = [item.get("name") if isinstance(item, dict) else item for item in found]
    else:
        found_names = []
    missing = discovery.get("missing_target_tables") or discovery.get("missing_tables") or []
    return {
        "target_tables": targets,
        "found_tables": [name for name in found_names if name][:80],
        "missing_target_tables": missing[:40] if isinstance(missing, list) else missing,
        "error_count": len(discovery.get("errors") or []),
        "errors": [_truncate(item, 220) for item in (discovery.get("errors") or [])[:5]],
    }


def compact_config_plan_for_ai(plan: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(plan, dict):
        return {}
    compact = deepcopy(plan)
    compact["run_instruction"] = _truncate(compact.get("run_instruction"), 900)
    compact["recommended_target_tables"] = (compact.get("recommended_target_tables") or [])[:12]
    compact["all_recommended_tables"] = (compact.get("all_recommended_tables") or [])[:18]
    compact["relation_chain"] = (compact.get("relation_chain") or [])[:12]
    compact["matched_field_mappings"] = _compact_knowledge_items(compact.get("matched_field_mappings") or [], PLAN_FIELD_MAPPING_LIMIT_AI)
    compact["field_dictionary_matches"] = _compact_knowledge_items(compact.get("field_dictionary_matches") or [], PLAN_FIELD_DICTIONARY_LIMIT_AI)
    compact["matched_rules"] = _compact_knowledge_items(compact.get("matched_rules") or [], PLAN_RULE_LIMIT_AI)
    compact["similar_cases"] = _compact_knowledge_items(compact.get("similar_cases") or [], PLAN_CASE_LIMIT_AI)
    compact["similar_case_summaries"] = [_truncate(item, 240) for item in (compact.get("similar_case_summaries") or [])[:PLAN_CASE_LIMIT_AI]]
    compact["structured_corrections"] = _compact_knowledge_items(compact.get("structured_corrections") or [], PLAN_CORRECTION_LIMIT_AI)
    compact["pending_confirmations"] = [_truncate(item, 220) for item in (compact.get("pending_confirmations") or [])[:12]]
    compact["missing_information"] = [_truncate(item, 180) for item in (compact.get("missing_information") or [])[:8]]
    compact["required_fields"] = _compact_required_fields(compact.get("required_fields") or {})
    planning_signals = compact.get("planning_signals") or {}
    compact["planning_signals"] = {
        "sheet_names": (planning_signals.get("sheet_names") or [])[:8],
        "headers": (planning_signals.get("headers") or [])[:40],
    }
    return _drop_empty(compact)


def compact_target_table_profiles(profiles: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for table_name, profile in profiles.items():
        if not isinstance(profile, dict):
            continue
        fields: dict[str, Any] = {}
        candidates = []
        for order, (field, stat) in enumerate((profile.get("fields") or {}).items()):
            if not isinstance(stat, dict) or not _keep_profile_field(field, stat, profile):
                continue
            candidates.append((_profile_field_priority(field, stat, profile), order, field, stat))
        candidates.sort(key=lambda item: (-item[0], item[1]))
        for _, _, field, stat in candidates[:PROFILE_FIELD_LIMIT_AI]:
            fields[field] = _compact_profile_field(stat)
        tail_rows = [_compact_tail_row(row, fields) for row in (profile.get("tail_rows") or [])[-PROFILE_TAIL_ROW_LIMIT_AI:]]
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
        omitted = max(0, len(candidates) - len(fields))
        if omitted:
            compact[table_name]["omitted_profile_fields"] = omitted
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


def _relationship_priority(relation: dict[str, Any], targets: set[str], recommended: set[str]) -> float:
    from_table = relation.get("from_table")
    to_table = relation.get("to_table")
    confidence = float(relation.get("confidence") or 0)
    score = confidence
    if from_table in targets:
        score += 0.35
    if to_table in targets:
        score += 0.25
    if from_table in recommended or to_table in recommended:
        score += 0.15
    if int(relation.get("hop") or 1) <= 1:
        score += 0.1
    return score


def _compact_top_level_knowledge(context: dict[str, Any]) -> None:
    limits = {
        "matched_field_mappings": 20,
        "field_dictionary_matches": 24,
        "matched_rules": 8,
        "similar_cases": 4,
        "structured_corrections": 6,
    }
    for key, limit in limits.items():
        if key in context:
            context[key] = _compact_knowledge_items(context.get(key) or [], limit)
    if "similar_case_summaries" in context:
        context["similar_case_summaries"] = [_truncate(item, 240) for item in (context.get("similar_case_summaries") or [])[:4]]


def _compact_knowledge_items(items: list[Any], limit: int) -> list[Any]:
    return [_truncate_deep(item) for item in items[:limit]]


def _compact_required_fields(required_fields: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    if not isinstance(required_fields, dict):
        return compact
    for table_name, fields in required_fields.items():
        if isinstance(fields, list):
            compact[table_name] = fields[:18]
        elif isinstance(fields, dict):
            compact[table_name] = dict(list(fields.items())[:18])
        else:
            compact[table_name] = fields
    return compact


def _truncate_deep(value: Any, string_limit: int = KNOWLEDGE_STRING_LIMIT_AI) -> Any:
    if isinstance(value, str):
        return _truncate(value, string_limit)
    if isinstance(value, list):
        return [_truncate_deep(item, string_limit) for item in value[:20]]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if key in {"raw", "raw_text", "original_text", "full_text", "content"}:
                result[key] = _truncate(item, min(string_limit, 220))
            else:
                result[key] = _truncate_deep(item, string_limit)
        return _drop_empty(result)
    return value


def _drop_empty(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item not in (None, "", [], {})}


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
    compact: dict[str, Any] = {}
    roles = stat.get("roles") or []
    important_values = bool(stat.get("allocation_role") or stat.get("id_strategy") or stat.get("reference_table") or "lookup_ref" in roles)
    for key in PROFILE_FIELD_KEYS:
        value = stat.get(key)
        if value in (None, "", []):
            continue
        if key in {"sample_values", "top_values"} and not important_values:
            continue
        compact[key] = value
    if "sample_values" in compact:
        compact["sample_values"] = compact["sample_values"][:PROFILE_SAMPLE_VALUE_LIMIT_AI]
    if "top_values" in compact:
        compact["top_values"] = compact["top_values"][:PROFILE_TOP_VALUE_LIMIT_AI]
    if "enum_values" in compact:
        compact["enum_values"] = compact["enum_values"][:PROFILE_ENUM_VALUE_LIMIT_AI]
    return compact


def _profile_field_priority(field: str, stat: dict[str, Any], profile: dict[str, Any]) -> int:
    score = 0
    roles = stat.get("roles") or []
    if field in (profile.get("primary_key") or []):
        score += 120
    if field == profile.get("group_key"):
        score += 110
    if stat.get("allocation_role"):
        score += 100
    if stat.get("id_strategy") in {"new", "new_or_reuse"}:
        score += 90
    if stat.get("reference_table") or "lookup_ref" in roles:
        score += 75
    if "foreign_key_candidate" in roles:
        score += 55
    if any(keyword in field for keyword in PROFILE_PRIORITY_KEYWORDS) or any(keyword in field.lower() for keyword in PROFILE_PRIORITY_KEYWORDS):
        score += 35
    if stat.get("enum_values"):
        score += 15
    if stat.get("next_value") is not None:
        score += 10
    return score


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
