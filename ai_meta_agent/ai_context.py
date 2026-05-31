from __future__ import annotations

from typing import Any

from .habits import habit_context
from .models import Habit, Manifest, SchemaBundle, WorkbookIR


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
) -> dict[str, Any]:
    table_names = list(schema.tables.keys())
    context = {
        "project": manifest.project,
        "mode": manifest.mode,
        "instructions": [
            "Return strict JSON matching Patch schema.",
            "Every operation must include target_table, source_ref, reason, confidence, risk_level.",
            "Do not invent objects not present in planning rows or habits.",
            "When planning_item_resolution is present, use it as evidence for product reward type, content ID, and quantity.",
            "Mark low-confidence or high-risk operations as needs_confirmation=true.",
            "If an activity template, field mappings, relationships, and planning rows provide enough evidence, generate a supervised patch even when some fields still need confirmation.",
            "Do not return an empty patch only because non-critical fields are missing; write the evidenced fields and leave uncertain values out or mark the operation high risk with needs_confirmation=true.",
            "Only return zero operations when there is no target table path, no usable primary key or insert row evidence, or the schema has no writable target table for the detected activity.",
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
        "workbooks": [
            {
                "source_id": workbook.source_id,
                "source_type": workbook.source_type,
                "path": workbook.path,
                "url": workbook.url,
                "sheets": [
                    {
                        "name": sheet.name,
                        "max_row": sheet.max_row,
                        "max_column": sheet.max_column,
                        "header_row": sheet.header_row,
                        "headers": sheet.headers,
                        "hidden_rows": sheet.hidden_rows[:20],
                        "hidden_columns": sheet.hidden_columns[:20],
                        "merged_ranges": sheet.merged_ranges[:20],
                        "sample_rows": sheet.sample_rows[:20],
                    }
                    for sheet in workbook.sheets
                ],
            }
            for workbook in workbooks
        ],
        "matched_habits": habit_context(habits),
        "target_tables": table_names,
    }
    if item_resolution:
        context["planning_item_resolution"] = item_resolution
    if experience:
        context.update(
            {
                "matched_activity_templates": experience.get("matched_activity_templates", []),
                "matched_field_mappings": experience.get("matched_field_mappings", []),
                "matched_rules": experience.get("matched_rules", []),
                "similar_cases": experience.get("similar_cases", []),
                "config_plan": experience.get("config_plan", {}),
            }
        )
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
