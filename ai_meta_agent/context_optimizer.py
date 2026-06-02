from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from .planning_parser import compact_structured_planning_for_ai


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
PROFILE_FIELD_LIMIT_AI = 7
PROFILE_TAIL_ROW_LIMIT_AI = 1
PROFILE_SAMPLE_VALUE_LIMIT_AI = 2
PROFILE_TOP_VALUE_LIMIT_AI = 2
PROFILE_ENUM_VALUE_LIMIT_AI = 5
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
    "num",
    "count",
    "weight",
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
RELATIONSHIP_LIMIT_AI = 18
PLAN_FIELD_MAPPING_LIMIT_AI = 8
PLAN_FIELD_DICTIONARY_LIMIT_AI = 10
PLAN_RULE_LIMIT_AI = 4
PLAN_CASE_LIMIT_AI = 2
PLAN_CORRECTION_LIMIT_AI = 3
KNOWLEDGE_STRING_LIMIT_AI = 160
FAST_CONTEXT_MAX_BYTES = 32 * 1024
FAST_TABLE_LIMIT_AI = 4
FAST_SCHEMA_FIELD_LIMIT_AI = 24
FAST_PROFILE_FIELD_LIMIT_AI = 2
FAST_RELATIONSHIP_LIMIT_AI = 6
FAST_PLANNING_ROW_LIMIT_AI = 22
MODEL_OPTIONAL_ZERO_FIELDS = {
    "reward": {"is_removal", "hero_limit"},
}


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
    if "structured_planning" in optimized:
        optimized["structured_planning"] = compact_structured_planning_for_ai(context.get("structured_planning") or {})
    if "planning_item_resolution" in optimized:
        optimized["planning_item_resolution"] = _planning_resolution_summary(context)
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
    return enforce_fast_context_budget(optimized)


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
        required_fields = _ai_required_fields(table_name, required_fields)
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
    _replace_plan_knowledge_with_counts(compact)
    compact["id_strategy"] = _compact_id_strategy(compact.get("id_strategy") or {})
    compact["pending_confirmations"] = [_truncate(item, 220) for item in (compact.get("pending_confirmations") or [])[:12]]
    compact["missing_information"] = [_truncate(item, 180) for item in (compact.get("missing_information") or [])[:8]]
    compact["required_fields"] = _compact_required_fields(compact.get("required_fields") or {})
    planning_signals = compact.get("planning_signals") or {}
    compact["planning_signals"] = {
        "sheet_names": (planning_signals.get("sheet_names") or [])[:8],
        "headers": (planning_signals.get("headers") or [])[:40],
    }
    return _drop_empty(compact)


def _compact_id_strategy(strategy: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(strategy, dict):
        return {}
    result: dict[str, Any] = {}
    if strategy.get("template_rule"):
        result["template_rule"] = _truncate(strategy.get("template_rule"), 500)
    field_rules = strategy.get("field_rules") or {}
    if isinstance(field_rules, dict):
        compact_rules = {}
        for table_name, rules in list(field_rules.items())[:6]:
            compact_rules[table_name] = [
                {
                    "field": item.get("field"),
                    "strategy": item.get("strategy"),
                    "risk_note": _truncate(item.get("risk_note"), 120),
                    "confidence": item.get("confidence"),
                }
                for item in (rules or [])[:3]
                if isinstance(item, dict)
            ]
        result["field_rules"] = _drop_empty(compact_rules)
    return _drop_empty(result)


def _replace_plan_knowledge_with_counts(plan: dict[str, Any]) -> None:
    for key in [
        "matched_field_mappings",
        "field_dictionary_matches",
        "matched_rules",
        "similar_cases",
        "similar_case_summaries",
        "structured_corrections",
    ]:
        value = plan.pop(key, None)
        if value:
            plan[f"{key}_count"] = len(value)


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


def enforce_fast_context_budget(context: dict[str, Any]) -> dict[str, Any]:
    if _json_bytes(context) <= FAST_CONTEXT_MAX_BYTES:
        return context
    compact = deepcopy(context)
    fast_tables = _fast_table_scope(compact)
    targets = set(fast_tables)
    compact["ai_target_tables"] = fast_tables
    compact["target_tables"] = fast_tables
    compact["schema"] = _fast_schema_for_ai(compact.get("schema") or {}, targets)
    compact["target_table_profiles"] = _fast_target_table_profiles(compact.get("target_table_profiles") or {}, targets)
    compact["relationship_map"] = _fast_relationship_map(compact.get("relationship_map") or {})
    compact["planning_evidence"] = _fast_planning_evidence(compact.get("planning_evidence") or [])
    compact["config_plan"] = compact_config_plan_for_ai(compact.get("config_plan") or {})
    compact["matched_field_mappings"] = _compact_knowledge_items(compact.get("matched_field_mappings") or [], 4)
    compact["field_dictionary_matches"] = _compact_knowledge_items(compact.get("field_dictionary_matches") or [], 5)
    compact["matched_rules"] = _compact_knowledge_items(compact.get("matched_rules") or [], 3)
    compact["structured_corrections"] = _compact_knowledge_items(compact.get("structured_corrections") or [], 2)
    compact["similar_cases"] = _compact_knowledge_items(compact.get("similar_cases") or [], 1)
    compact["similar_case_summaries"] = [_truncate_deep(item, 120) for item in (compact.get("similar_case_summaries") or [])[:1]]
    optimization = compact.setdefault("context_optimization", {})
    optimization["mode"] = "fast_budget_local_evidence_first"
    optimization["max_context_bytes"] = FAST_CONTEXT_MAX_BYTES
    optimization["ai_target_tables"] = fast_tables
    optimization.setdefault("notes", []).append("上下文超过快速预算时，只发送关键写表字段和 ID 依据；完整表画像仍保存在本地用于确定性后处理。")
    if _json_bytes(compact) > FAST_CONTEXT_MAX_BYTES:
        compact = _enforce_hard_context_budget(compact)
    return compact


def _enforce_hard_context_budget(context: dict[str, Any]) -> dict[str, Any]:
    compact = deepcopy(context)
    if "structured_planning" in compact:
        compact["structured_planning"] = compact_structured_planning_for_ai(compact.get("structured_planning") or {}, item_limit=48)
    compact["planning_evidence"] = _hard_planning_evidence(compact.get("planning_evidence") or [])
    compact["relationship_map"] = _hard_relationship_map(compact.get("relationship_map") or {})
    compact["config_plan"] = _hard_config_plan(compact.get("config_plan") or {})
    compact["matched_activity_templates"] = _hard_activity_templates(compact.get("matched_activity_templates") or [])
    compact["matched_field_mappings"] = _hard_field_mappings(compact.get("matched_field_mappings") or [])
    compact["field_dictionary_matches"] = _hard_field_dictionary(compact.get("field_dictionary_matches") or [])
    compact["matched_rules"] = _hard_rules(compact.get("matched_rules") or [])
    compact["structured_corrections"] = _hard_corrections(compact.get("structured_corrections") or [])
    compact["similar_cases"] = []
    compact["similar_case_summaries"] = [_truncate_deep(item, 100) for item in (compact.get("similar_case_summaries") or [])[:1]]
    compact["matched_habits"] = (compact.get("matched_habits") or [])[:2]
    optimization = compact.setdefault("context_optimization", {})
    optimization["mode"] = "hard_fast_budget_local_evidence_first"
    optimization["hard_budget_applied"] = True
    return compact


def _hard_planning_evidence(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for item in items[:1]:
        rows = []
        for row in (item.get("rows") or [])[:18]:
            rows.append({key: _truncate(value, 80) for key, value in row.items()})
        result.append(_drop_empty({"source_id": item.get("source_id"), "sheet": item.get("sheet"), "rows": rows, "row_count": len(rows)}))
    return result


def _hard_relationship_map(result: dict[str, Any]) -> dict[str, Any]:
    return _drop_empty(
        {
            "target_tables": result.get("target_tables") or [],
            "recommended_tables": (result.get("recommended_tables") or [])[:6],
            "relations": (result.get("relations") or [])[:4],
        }
    )


def _hard_config_plan(plan: dict[str, Any]) -> dict[str, Any]:
    return _drop_empty(
        {
            "activity_type": plan.get("activity_type"),
            "confidence": plan.get("confidence"),
            "run_instruction": _truncate(plan.get("run_instruction"), 500),
            "current_target_tables": (plan.get("current_target_tables") or [])[:8],
            "relation_chain": (plan.get("relation_chain") or [])[:8],
            "required_fields": _compact_required_fields(plan.get("required_fields") or {}),
            "id_strategy": _compact_id_strategy(plan.get("id_strategy") or {}),
            "missing_information": [_truncate(item, 120) for item in (plan.get("missing_information") or [])[:5]],
            "pending_confirmations": [_truncate(item, 120) for item in (plan.get("pending_confirmations") or [])[:5]],
            "readiness": plan.get("readiness") or {},
        }
    )


def _hard_activity_templates(items: list[Any]) -> list[Any]:
    result = []
    for item in items[:1]:
        if isinstance(item, dict):
            result.append(_drop_empty({"name": item.get("name"), "target_tables": (item.get("target_tables") or [])[:8], "relation_chain": (item.get("relation_chain") or [])[:8]}))
    return result


def _hard_field_mappings(items: list[Any]) -> list[Any]:
    result = []
    for item in items[:3]:
        if isinstance(item, dict):
            result.append(_drop_empty({"source_aliases": (item.get("source_aliases") or [])[:4], "target_table": item.get("target_table"), "target_field": item.get("target_field"), "confidence": item.get("confidence")}))
    return result


def _hard_field_dictionary(items: list[Any]) -> list[Any]:
    result = []
    for item in items[:3]:
        if isinstance(item, dict):
            result.append(_drop_empty({"target_table": item.get("target_table"), "target_field": item.get("target_field"), "description": _truncate(item.get("description"), 100), "id_strategy": item.get("id_strategy"), "reference_table": item.get("reference_table")}))
    return result


def _hard_rules(items: list[Any]) -> list[Any]:
    result = []
    for item in items[:2]:
        if isinstance(item, dict):
            result.append(_drop_empty({"title": _truncate(item.get("title") or item.get("summary_title") or item.get("name"), 90), "text": _truncate(item.get("text") or item.get("rule") or item.get("content"), 180), "applies_to_tables": (item.get("applies_to_tables") or [])[:6]}))
    return result


def _hard_corrections(items: list[Any]) -> list[Any]:
    result = []
    for item in items[:1]:
        if isinstance(item, dict):
            result.append(
                _drop_empty(
                    {
                        "target_tables": (item.get("target_tables") or [])[:6],
                        "target_fields": (item.get("target_fields") or [])[:12],
                        "error_pattern": _truncate(item.get("error_pattern"), 140),
                        "correct_practice": _truncate(item.get("correct_practice"), 220),
                        "avoid_next_time": [_truncate(value, 120) for value in (item.get("avoid_next_time") or [])[:3]],
                    }
                )
            )
    return result


def _fast_table_scope(context: dict[str, Any]) -> list[str]:
    """Pick the tables the model should actively reason about.

    The full run still keeps all selected tables locally for validation and
    preview generation. This model-facing scope trims reference-only tables
    when the project selected many related sheets but only a few have direct
    write evidence.
    """
    available = set((context.get("schema") or {}).get("tables") or {})
    selected = [table for table in (context.get("target_tables") or []) if table in available]
    plan = context.get("config_plan") or {}
    priority: dict[str, int] = {}

    def bump(table: Any, score: int) -> None:
        name = str(table or "").strip()
        if name and name in available:
            priority[name] = max(priority.get(name, 0), score)

    for index, table in enumerate(plan.get("relation_chain") or []):
        bump(table, 120 - index)
    for table in (plan.get("required_fields") or {}):
        bump(table, 115)
    if context.get("resolved_items"):
        for table in ["activity", "active_shop", "reward", "goods"]:
            bump(table, 112)
    for item in context.get("field_dictionary_matches") or []:
        bump(item.get("target_table"), 100)
    for item in context.get("matched_field_mappings") or []:
        bump(item.get("target_table"), 95)
    for item in context.get("structured_corrections") or []:
        for table in item.get("target_tables") or []:
            bump(table, 90)
    for table, profile in (context.get("target_table_profiles") or {}).items():
        if profile.get("next_values"):
            bump(table, 80)
    for table in selected:
        bump(table, 70)
    if plan.get("activity_type"):
        bump("activity", 110)

    ordered = sorted(
        priority,
        key=lambda table: (
            -priority[table],
            selected.index(table) if table in selected else 999,
            table,
        ),
    )
    if not ordered:
        ordered = selected
    return ordered[:FAST_TABLE_LIMIT_AI]


def _fast_schema_for_ai(schema: dict[str, Any], targets: set[str]) -> dict[str, Any]:
    tables: dict[str, Any] = {}
    for table_name, table in (schema.get("tables") or {}).items():
        if targets and table_name not in targets:
            continue
        fields = _priority_fields(table_name, table.get("field_names") or [], table, FAST_SCHEMA_FIELD_LIMIT_AI)
        required = [field for field in _ai_required_fields(table_name, table.get("required_fields") or []) if field in fields]
        compact = {
            "primary_key": table.get("primary_key") or [],
            "group_key": table.get("group_key"),
            "ai_write_permission": table.get("ai_write_permission"),
            "field_names": fields,
            "required_fields": required[:12],
            "preserve_fields": [field for field in (table.get("preserve_fields") or []) if field in fields],
            "block_update_fields": [field for field in (table.get("block_update_fields") or []) if field in fields],
        }
        for key in ["field_types", "default_values"]:
            values = table.get(key) or {}
            if isinstance(values, dict):
                selected = {field: values[field] for field in fields if field in values}
                if selected:
                    compact[key] = selected
        tables[table_name] = _drop_empty(compact)
    return {"tables": tables, "risk": schema.get("risk") or {}}


def _priority_fields(table_name: str, fields: list[str], table: dict[str, Any], limit: int) -> list[str]:
    required = _ai_required_fields(table_name, table.get("required_fields") or [])
    anchors = [*(table.get("primary_key") or []), table.get("group_key"), *required]
    selected: list[str] = []
    seen: set[str] = set()
    for field in anchors:
        if field and field in fields and field not in seen:
            seen.add(field)
            selected.append(field)
    candidates = [field for field in fields if field not in seen]
    candidates.sort(key=lambda field: (-_field_name_priority(field), fields.index(field)))
    for field in candidates:
        if len(selected) >= limit:
            break
        seen.add(field)
        selected.append(field)
    return selected


def _ai_required_fields(table_name: str, required_fields: list[str]) -> list[str]:
    optional_zero_fields = MODEL_OPTIONAL_ZERO_FIELDS.get(table_name, set())
    return [field for field in required_fields if field not in optional_zero_fields]


def _field_name_priority(field: str) -> int:
    text = str(field)
    score = 0
    lowered = text.lower()
    if lowered in {"type", "num"}:
        score += 120
    for keyword in PROFILE_PRIORITY_KEYWORDS:
        if keyword in text or keyword in lowered:
            score += 10
    if any(value in lowered for value in ("id", "type", "group", "reward", "goods", "cost", "price", "order", "time", "form", "list")):
        score += 20
    if lowered.startswith(("type_", "reward_", "num_", "weight_")):
        score += 45
    if any(value in lowered for value in ("num", "count", "weight")) or any(value in text for value in ("数量", "权重", "道具数量")):
        score += 35
    return score


def _fast_target_table_profiles(profiles: dict[str, Any], targets: set[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for table_name, profile in profiles.items():
        if targets and table_name not in targets:
            continue
        fields = {}
        candidates = []
        for order, (field, stat) in enumerate((profile.get("fields") or {}).items()):
            if not isinstance(stat, dict):
                continue
            candidates.append((_profile_field_priority(field, stat, profile), order, field, stat))
        candidates.sort(key=lambda item: (-item[0], item[1]))
        for _, _, field, stat in candidates[:FAST_PROFILE_FIELD_LIMIT_AI]:
            fields[field] = _fast_profile_field(stat)
        result[table_name] = _drop_empty(
            {
                "primary_key": profile.get("primary_key") or [],
                "group_key": profile.get("group_key"),
                "next_values": profile.get("next_values") or {},
                "fields": fields,
            }
        )
    return result


def _fast_profile_field(stat: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "field",
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
    ]
    compact = {key: stat.get(key) for key in keys if stat.get(key) not in (None, "", [])}
    if "enum_values" in compact:
        compact["enum_values"] = compact["enum_values"][:3]
    return compact


def _fast_relationship_map(result: dict[str, Any]) -> dict[str, Any]:
    compact = dict(result)
    compact["relations"] = (result.get("relations") or [])[:FAST_RELATIONSHIP_LIMIT_AI]
    if "ai_review" in compact:
        compact.pop("ai_review", None)
    return _drop_empty(compact)


def _fast_planning_evidence(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact_items = []
    for item in items[:2]:
        rows = []
        source_rows = list(item.get("rows") or [])
        source_rows.sort(key=lambda row: (-_planning_row_priority(row), int(row.get("__row") or 0)))
        for row in source_rows[:FAST_PLANNING_ROW_LIMIT_AI]:
            rows.append({key: _truncate(value, 100) for key, value in row.items()})
        compact_items.append(
            {
                "source_id": item.get("source_id"),
                "sheet": item.get("sheet"),
                "header_row": item.get("header_row"),
                "rows": rows,
                "row_count": len(rows),
            }
        )
    return compact_items


def _planning_row_priority(row: dict[str, Any]) -> int:
    text = " ".join(str(value) for key, value in row.items() if key != "__row" and value not in (None, ""))
    keys = " ".join(str(key) for key in row if key != "__row")
    score = 0
    if any(keyword in text or keyword in keys for keyword in ["商品", "商品名", "道具", "道具数量", "价格", "限购", "商店组", "排序", "分组"]):
        score += 90
    if any(keyword in text or keyword in keys for keyword in ["活动开始", "活动结束", "活动时间", "开启条件", "是否启用", "开关名", "活动类型"]):
        score += 55
    if any(keyword in text for keyword in ["填写规范", "字段说明", "工具会", "不要删除", "标签规范"]):
        score -= 45
    if any(keyword in text or keyword in keys for keyword in ["鍟嗗搧", "閬撳叿", "濂栧姳", "商品", "道具", "奖励"]):
        score += 60
    if any(keyword in text or keyword in keys for keyword in ["浠锋牸", "闄愯喘", "消耗", "价格", "限购"]):
        score += 45
    if any(keyword in text or keyword in keys for keyword in ["娲诲姩", "活动", "time", "时间", "开启条件"]):
        score += 35
    if any(keyword in text or keyword in keys for keyword in ["group", "缁?", "组", "form_list", "商店组"]):
        score += 30
    if any(value in str(row.get("字段说明") or "").lower() for value in ["activity_id", "cost_id", "type"]):
        score -= 10
    if len(row) > 12:
        score -= 5
    return score


def build_context_budget(original: dict[str, Any], optimized: dict[str, Any]) -> dict[str, Any]:
    original_bytes = _json_bytes(original)
    optimized_bytes = _json_bytes(optimized)
    value_before = _sample_row_total(original.get("workbooks") or [], value_only=True)
    value_after = _sample_row_total(optimized.get("workbooks") or [], value_only=True)
    planning_after = _planning_evidence_row_total(optimized.get("planning_evidence") or [])
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": (optimized.get("context_optimization") or {}).get("mode") or "deterministic_local_index_first",
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
        "matched_field_mappings": 4,
        "field_dictionary_matches": 5,
        "matched_rules": 3,
        "similar_cases": 1,
        "structured_corrections": 1,
    }
    for key, limit in limits.items():
        if key in context:
            context[key] = _compact_knowledge_items(context.get(key) or [], limit)
    if "similar_case_summaries" in context:
        context["similar_case_summaries"] = [_truncate_deep(item, 120) for item in (context.get("similar_case_summaries") or [])[:1]]


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
            sheets.append(
                {
                    "name": sheet.get("name"),
                    "max_row": sheet.get("max_row"),
                    "max_column": sheet.get("max_column"),
                    "header_row": sheet.get("header_row"),
                    "headers": (sheet.get("headers") or [])[:50],
                    "sample_row_count": sheet.get("sample_row_count"),
                    "sample_rows_omitted": sheet.get("sample_row_count") or 0,
                    "sample_rows": [],
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
            rows = _compact_planning_rows(sheet.get("sample_rows") or [], limit=80)
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
    return [_compact_resolved_item(item) for item in (resolution.get("matches") or [])[:48]]


def _unresolved_item_candidates(context: dict[str, Any]) -> list[dict[str, Any]]:
    resolution = context.get("planning_item_resolution") or {}
    result = []
    for item in (resolution.get("missing") or [])[:24]:
        result.append(
            {
                "product_name": item.get("product_name"),
                "planning_ref": item.get("planning_ref"),
                "reason": item.get("reason"),
                "candidates": (item.get("candidates") or [])[:3],
            }
        )
    return result


def _planning_resolution_summary(context: dict[str, Any]) -> dict[str, Any]:
    resolution = context.get("planning_item_resolution") or {}
    return _drop_empty(
        {
            "enabled": resolution.get("enabled"),
            "summary": resolution.get("summary") or {},
            "warnings": (resolution.get("warnings") or [])[:5],
            "column_mappings": (resolution.get("column_mappings") or [])[:6],
            "notes": "Full item matches, duplicate candidates, and raw value rows stay in local run files; AI receives compact resolved_items only.",
        }
    )


def _compact_resolved_item(item: dict[str, Any]) -> dict[str, Any]:
    return _drop_empty(
        {
            "product_name": item.get("product_name"),
            "reward_type": item.get("reward_type"),
            "content_id": item.get("content_id"),
            "num": item.get("num"),
            "confidence": item.get("confidence"),
            "needs_confirmation": item.get("needs_confirmation"),
            "planning_ref": _compact_source_ref(item.get("planning_ref") or {}),
            "value_ref": _compact_source_ref(item.get("value_ref") or {}),
        }
    )


def _compact_source_ref(ref: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(ref, dict):
        return {}
    return _drop_empty(
        {
            "workbook": ref.get("workbook"),
            "sheet": ref.get("sheet"),
            "row": ref.get("row"),
            "field": ref.get("field"),
        }
    )


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
