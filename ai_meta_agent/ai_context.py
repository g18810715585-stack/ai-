from __future__ import annotations

from typing import Any

from .habits import habit_context
from .models import Habit, Manifest, SchemaBundle, WorkbookIR
from .planning_parser import build_structured_planning

PLANNING_CONTEXT_SAMPLE_ROWS = 200
VALUE_CONTEXT_SAMPLE_ROWS = 5000


def _truncate(value: Any, limit: int = 300) -> Any:
    if isinstance(value, str):
        return value if len(value) <= limit else f"{value[:limit]}..."
    return value


def _compact_row(row: dict[str, Any], limit: int = 60) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, value in row.items():
        if key == "__row":
            compact[key] = value
            continue
        label = str(key or "").strip()
        if not label or value in (None, ""):
            continue
        compact[label] = _truncate(value, 180)
        if len(compact) >= limit:
            break
    return compact


def _sample_row_limit(workbook: WorkbookIR) -> int:
    source_hint = " ".join(
        str(value or "").lower()
        for value in [workbook.source_id, workbook.path, workbook.url]
    )
    if any(keyword in source_hint for keyword in ["item_base", "value", "价值"]):
        return VALUE_CONTEXT_SAMPLE_ROWS
    return PLANNING_CONTEXT_SAMPLE_ROWS


def _compact_workbooks(workbooks: list[WorkbookIR]) -> list[dict[str, Any]]:
    result = []
    for workbook in workbooks:
        sample_limit = _sample_row_limit(workbook)
        sheets = []
        for sheet in workbook.sheets:
            headers = [str(header).strip() for header in sheet.headers if str(header).strip()]
            sample_rows = [_compact_row(row) for row in sheet.sample_rows[:sample_limit]]
            sheets.append(
                {
                    "name": sheet.name,
                    "max_row": sheet.max_row,
                    "max_column": sheet.max_column,
                    "header_row": sheet.header_row,
                    "headers": headers[:120],
                    "hidden_rows": sheet.hidden_rows[:20],
                    "hidden_columns": sheet.hidden_columns[:20],
                    "merged_ranges": sheet.merged_ranges[:20],
                    "sample_row_count": len(sheet.sample_rows),
                    "sample_rows_omitted": max(0, len(sheet.sample_rows) - len(sample_rows)),
                    "sample_rows": sample_rows,
                }
            )
        result.append(
            {
                "source_id": workbook.source_id,
                "source_type": workbook.source_type,
                "path": workbook.path,
                "url": workbook.url,
                "sheets": sheets,
            }
        )
    return result


def _compact_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    return {
        "mapping_id": mapping.get("mapping_id"),
        "source_aliases": (mapping.get("source_aliases") or [])[:8],
        "matched_aliases": (mapping.get("matched_aliases") or [])[:8],
        "target_table": mapping.get("target_table"),
        "target_field": mapping.get("target_field"),
        "target_field_exists": mapping.get("target_field_exists"),
        "confidence": mapping.get("confidence"),
        "evidence": [_truncate(item, 160) for item in (mapping.get("evidence") or [])[:2]],
    }


def _compact_dictionary(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "dictionary_id": entry.get("dictionary_id"),
        "target_table": entry.get("target_table"),
        "target_field": entry.get("target_field"),
        "description": _truncate(entry.get("description"), 220),
        "source_aliases": (entry.get("source_aliases") or [])[:8],
        "matched_aliases": (entry.get("matched_aliases") or [])[:8],
        "writable": entry.get("writable"),
        "id_strategy": entry.get("id_strategy"),
        "reference_table": entry.get("reference_table"),
        "risk_note": _truncate(entry.get("risk_note"), 180),
        "confidence": entry.get("confidence"),
    }


def _compact_rule(rule: dict[str, Any]) -> dict[str, Any]:
    return {
        "rule_id": rule.get("rule_id") or rule.get("experience_id"),
        "title": _truncate(rule.get("title") or rule.get("summary_title") or rule.get("name"), 120),
        "text": _truncate(rule.get("text") or rule.get("rule") or rule.get("content"), 500),
        "scenario_tags": (rule.get("scenario_tags") or [])[:8],
        "applies_to_tables": (rule.get("applies_to_tables") or [])[:12],
        "confidence": rule.get("confidence"),
        "match_score": rule.get("match_score"),
        "evidence": [_truncate(item, 120) for item in (rule.get("evidence") or [])[:2]],
    }


def _compact_template(template: dict[str, Any]) -> dict[str, Any]:
    return {
        "template_id": template.get("template_id"),
        "name": template.get("name"),
        "target_tables": (template.get("target_tables") or [])[:16],
        "relation_chain": (template.get("relation_chain") or [])[:16],
        "required_fields": template.get("required_fields") or {},
        "confidence": template.get("confidence"),
        "match_score": template.get("match_score"),
    }


def _compact_case(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": case.get("case_id"),
        "decision": case.get("decision"),
        "target_tables": (case.get("target_tables") or [])[:12],
        "operation_count": case.get("operation_count"),
        "correction": _truncate(case.get("correction") or case.get("note"), 400),
        "lessons": [_truncate(item, 160) for item in (case.get("case_review", {}).get("lessons") or [])[:5]],
        "match_score": case.get("match_score"),
    }


def _compact_correction(correction: dict[str, Any]) -> dict[str, Any]:
    return {
        "correction_id": correction.get("correction_id"),
        "activity_types": (correction.get("activity_types") or [])[:6],
        "target_tables": (correction.get("target_tables") or [])[:12],
        "target_fields": (correction.get("target_fields") or [])[:20],
        "error_pattern": _truncate(correction.get("error_pattern"), 220),
        "correct_practice": _truncate(correction.get("correct_practice"), 360),
        "avoid_next_time": [_truncate(item, 160) for item in (correction.get("avoid_next_time") or [])[:6]],
        "confidence": correction.get("confidence"),
        "match_score": correction.get("match_score"),
    }


def _compact_config_plan(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "activity_type": plan.get("activity_type"),
        "activity_template_id": plan.get("activity_template_id"),
        "confidence": plan.get("confidence"),
        "run_instruction": _truncate(plan.get("run_instruction"), 1200),
        "current_target_tables": plan.get("current_target_tables", []),
        "recommended_target_tables": plan.get("recommended_target_tables", [])[:16],
        "auto_included_target_tables": plan.get("auto_included_target_tables", []),
        "all_recommended_tables": plan.get("all_recommended_tables", [])[:24],
        "relation_chain": plan.get("relation_chain", [])[:16],
        "required_fields": plan.get("required_fields", {}),
        "id_strategy": plan.get("id_strategy") or {},
        "matched_field_mappings": [_compact_mapping(item) for item in (plan.get("matched_field_mappings") or [])[:24]],
        "field_dictionary_matches": [_compact_dictionary(item) for item in (plan.get("field_dictionary_matches") or [])[:30]],
        "matched_rules": [_compact_rule(item) for item in (plan.get("matched_rules") or [])[:10]],
        "similar_cases": [_compact_case(item) for item in (plan.get("similar_cases") or [])[:5]],
        "similar_case_summaries": (plan.get("similar_case_summaries") or [])[:5],
        "structured_corrections": [_compact_correction(item) for item in (plan.get("structured_corrections") or [])[:8]],
        "missing_information": [_truncate(item, 180) for item in (plan.get("missing_information") or [])[:10]],
        "pending_confirmations": (plan.get("pending_confirmations") or [])[:20],
        "readiness": plan.get("readiness") or {},
        "planning_signals": {
            "sheet_names": (plan.get("planning_signals", {}).get("sheet_names") or [])[:12],
            "headers": (plan.get("planning_signals", {}).get("headers") or [])[:80],
        },
        "safety": plan.get("safety"),
    }


def _compact_experience(experience: dict[str, Any] | None) -> dict[str, Any] | None:
    if not experience:
        return None
    return {
        "matched_activity_templates": [_compact_template(item) for item in experience.get("matched_activity_templates", [])[:5]],
        "matched_field_mappings": [_compact_mapping(item) for item in experience.get("matched_field_mappings", [])[:30]],
        "field_dictionary_matches": [_compact_dictionary(item) for item in experience.get("field_dictionary_matches", [])[:40]],
        "matched_rules": [_compact_rule(item) for item in experience.get("matched_rules", [])[:12]],
        "similar_cases": [_compact_case(item) for item in experience.get("similar_cases", [])[:6]],
        "similar_case_summaries": (experience.get("similar_case_summaries") or [])[:6],
        "structured_corrections": [_compact_correction(item) for item in experience.get("structured_corrections", [])[:10]],
        "config_plan": _compact_config_plan(experience.get("config_plan") or {}),
    }


def _relationship_candidates(schema: SchemaBundle) -> list[dict[str, str]]:
    primary_by_field: dict[str, str] = {}
    for table_name, table in schema.tables.items():
        for field in table.primary_key:
            primary_by_field[field] = table_name

    candidates: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for table_name, table in schema.tables.items():
        for field in table.fields:
            target_table = primary_by_field.get(field)
            if not target_table or target_table == table_name:
                continue
            key = (table_name, field, target_table)
            if key in seen:
                continue
            seen.add(key)
            candidates.append({"from_table": table_name, "field": field, "to_table": target_table})
    return candidates


def build_minimal_context(
    manifest: Manifest,
    schema: SchemaBundle,
    workbooks: list[WorkbookIR],
    habits: list[Habit],
    experience: dict[str, Any] | None = None,
    item_resolution: dict[str, Any] | None = None,
    target_table_profiles: dict[str, Any] | None = None,
) -> dict[str, Any]:
    table_names = list(schema.tables.keys())
    context = {
        "project": manifest.project,
        "mode": manifest.mode,
        "run_instruction": _truncate(manifest.run_instruction, 2000),
        "instructions": [
            "Return strict JSON matching Patch schema.",
            "Every operation must include target_table, source_ref, reason, confidence, risk_level.",
            "Do not invent objects not present in planning rows or habits.",
            "When planning_item_resolution is present, use it as evidence for product reward type, content ID, and quantity.",
            "When structured_planning is present, use it as the primary evidence for activity fields, shop groups, item prices, purchase limits, sort order, labels, and planning quantities.",
            "For exchange shop drafts, active_shop rows should use structured_planning.shop_groups and structured_planning.shop_items instead of guessing from product names only.",
            "Mark low-confidence or high-risk operations as needs_confirmation=true.",
            "If an activity template, field mappings, relationships, and planning rows provide enough evidence, generate a supervised patch even when some fields still need confirmation.",
            "Do not return an empty patch only because non-critical fields are missing; write the evidenced fields and leave uncertain values out or mark the operation high risk with needs_confirmation=true.",
            "Only return zero operations when there is no target table path, no usable primary key or insert row evidence, or the schema has no writable target table for the detected activity.",
            "Use target_table_profiles as the current original-table state: next_values are based on the bottom-most existing data row for generated primary keys/group keys, enum_values for valid existing options, tail_rows for recent writing style, and lookup fields only as reference evidence.",
            "For activity.id, target_table_profiles may use the last regular activity ID before the high-value season/cross-server ID region; follow next_value_basis instead of max_numeric.",
            "If a needed generated ID/group has no target_table_profiles baseline, return a placeholder plus a pending confirmation instead of inventing a number.",
            "Keep patch output minimal: include only fields that should be written, never echo full original rows, and omit null, blank, unchanged, or placeholder fields.",
        ],
        "schema": {
            "tables": {
                table_name: {
                    "primary_key": table.primary_key,
                    "group_key": table.group_key,
                    "overwrite_strategy": table.overwrite_strategy,
                    "ai_write_permission": table.ai_write_permission,
                    "allow_update_fields": table.allow_update_fields,
                    "preserve_fields": table.preserve_fields,
                    "block_update_fields": table.block_update_fields,
                    "fields": {field: spec.model_dump(exclude_none=True) for field, spec in table.fields.items()},
                    "field_aliases": table.field_aliases,
                }
                for table_name, table in schema.tables.items()
            },
            "risk": schema.risk.model_dump(),
            "relationship_candidates": _relationship_candidates(schema),
        },
        "workbooks": _compact_workbooks(workbooks),
        "matched_habits": habit_context(habits),
        "target_tables": table_names,
    }
    if target_table_profiles:
        context["target_table_profiles"] = target_table_profiles
    if item_resolution:
        context["planning_item_resolution"] = item_resolution
        structured_planning = build_structured_planning(manifest, workbooks, item_resolution)
        if structured_planning.get("sources"):
            context["structured_planning"] = structured_planning
    compact_experience = _compact_experience(experience)
    if compact_experience:
        context.update(compact_experience)
    return context


def summarize_analysis(workbooks: list[WorkbookIR], schema: SchemaBundle, matched_habits: list[Habit]) -> str:
    lines = ["# Analysis Summary", ""]
    lines.append("## Workbooks")
    for workbook in workbooks:
        lines.append(f"- {workbook.source_id}: {len(workbook.sheets)} sheet(s)")
        for sheet in workbook.sheets:
            lines.append(f"  - {sheet.name}: {sheet.max_row} rows x {sheet.max_column} cols, header row {sheet.header_row}")
    lines.append("")
    lines.append("## Target Tables")
    for table_name, table in schema.tables.items():
        lines.append(f"- {table_name}: pk={table.primary_key}, strategy={table.overwrite_strategy}")
    lines.append("")
    lines.append("## Matched Habits")
    if not matched_habits:
        lines.append("- None")
    for habit in matched_habits:
        lines.append(f"- {habit.name} ({habit.confidence:.2f})")
    lines.append("")
    return "\n".join(lines)
