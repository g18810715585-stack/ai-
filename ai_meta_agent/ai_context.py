from __future__ import annotations

from typing import Any

from .habits import habit_context
from .models import Habit, Manifest, SchemaBundle, WorkbookIR


def build_minimal_context(manifest: Manifest, schema: SchemaBundle, workbooks: list[WorkbookIR], habits: list[Habit]) -> dict[str, Any]:
    table_names = list(schema.tables.keys())
    return {
        "project": manifest.project,
        "mode": manifest.mode,
        "instructions": [
            "Return strict JSON matching Patch schema.",
            "Every operation must include target_table, source_ref, reason, confidence, risk_level.",
            "Do not invent objects not present in planning rows or habits.",
            "Mark low-confidence or high-risk operations as needs_confirmation=true.",
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
