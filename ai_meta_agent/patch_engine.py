from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook

from .models import Manifest, Patch, PatchOperation, SchemaBundle, ValidationIssue, ValidationReport


@dataclass
class WorkbookState:
    source_path: Path
    preview_path: Path
    workbook: Workbook


def _headers(sheet: Any) -> list[str]:
    return [str(sheet.cell(1, col).value) for col in range(1, sheet.max_column + 1) if sheet.cell(1, col).value not in (None, "")]


def _header_index(sheet: Any) -> dict[str, int]:
    return {header: idx + 1 for idx, header in enumerate(_headers(sheet))}


def _ensure_sheet(workbook: Workbook, sheet_name: str, fields: list[str]) -> Any:
    if sheet_name in workbook.sheetnames:
        sheet = workbook[sheet_name]
    else:
        sheet = workbook.create_sheet(sheet_name)
    existing = _headers(sheet)
    if not existing:
        existing = fields
        for col, field in enumerate(existing, start=1):
            sheet.cell(1, col).value = field
    else:
        for field in fields:
            if field not in existing:
                existing.append(field)
                sheet.cell(1, len(existing)).value = field
    return sheet


def _row_dict(sheet: Any, row_idx: int) -> dict[str, Any]:
    index = _header_index(sheet)
    return {field: sheet.cell(row_idx, col).value for field, col in index.items()}


def _row_matches(row: dict[str, Any], match: dict[str, Any]) -> bool:
    return all(str(row.get(field)) == str(value) for field, value in match.items())


def _find_rows(sheet: Any, match: dict[str, Any]) -> list[int]:
    rows: list[int] = []
    for row_idx in range(2, sheet.max_row + 1):
        if _row_matches(_row_dict(sheet, row_idx), match):
            rows.append(row_idx)
    return rows


def _write_row(sheet: Any, row_idx: int, row: dict[str, Any]) -> None:
    index = _header_index(sheet)
    for field, value in row.items():
        if field not in index:
            next_col = sheet.max_column + 1
            sheet.cell(1, next_col).value = field
            index[field] = next_col
        sheet.cell(row_idx, index[field]).value = value


def _table_ref(manifest: Manifest, schema: SchemaBundle, table_name: str, base_dir: Path) -> tuple[Path, str]:
    ref = manifest.config_tables.get(table_name)
    table = schema.tables[table_name]
    if not ref:
        raise KeyError(f"Manifest missing config table path for {table_name}")
    source = Path(ref.path)
    if not source.is_absolute():
        source = (base_dir / source).resolve()
    return source, ref.sheet or table.sheet or table_name


def _open_states(manifest: Manifest, schema: SchemaBundle, patch: Patch, base_dir: Path, run_dir: Path) -> dict[str, WorkbookState]:
    states: dict[str, WorkbookState] = {}
    preview_dir = run_dir / "preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    for operation in patch.operations:
        source_path, _ = _table_ref(manifest, schema, operation.target_table, base_dir)
        key = str(source_path)
        if key in states:
            continue
        if not source_path.exists():
            workbook = Workbook()
            workbook.active.title = "Sheet1"
        else:
            workbook = load_workbook(source_path)
        preview_path = preview_dir / f"{source_path.stem}.preview{source_path.suffix or '.xlsx'}"
        states[key] = WorkbookState(source_path=source_path, preview_path=preview_path, workbook=workbook)
    return states


def _snapshot(workbook: Workbook) -> dict[str, list[dict[str, Any]]]:
    data: dict[str, list[dict[str, Any]]] = {}
    for sheet in workbook.worksheets:
        rows = []
        for row_idx in range(2, sheet.max_row + 1):
            row = _row_dict(sheet, row_idx)
            if any(value not in (None, "") for value in row.values()):
                rows.append(row)
        data[sheet.title] = rows
    return data


def _normalize_key(row: dict[str, Any], primary_key: list[str]) -> tuple[Any, ...]:
    return tuple(row.get(field) for field in primary_key)


def _diff_table(old_rows: list[dict[str, Any]], new_rows: list[dict[str, Any]], primary_key: list[str]) -> dict[str, Any]:
    if not primary_key:
        return {"old_count": len(old_rows), "new_count": len(new_rows)}
    old_map = {_normalize_key(row, primary_key): row for row in old_rows}
    new_map = {_normalize_key(row, primary_key): row for row in new_rows}
    inserted = [new_map[key] for key in new_map.keys() - old_map.keys()]
    deleted = [old_map[key] for key in old_map.keys() - new_map.keys()]
    changed = []
    for key in old_map.keys() & new_map.keys():
        if old_map[key] != new_map[key]:
            changed.append({"key": list(key), "before": old_map[key], "after": new_map[key]})
    return {"inserted": inserted, "deleted": deleted, "changed": changed}


def _validate_workbook(workbook: Workbook, schema: SchemaBundle) -> ValidationReport:
    report = ValidationReport()
    for table_name, table in schema.tables.items():
        sheet_name = table.sheet or table_name
        if sheet_name not in workbook.sheetnames:
            continue
        sheet = workbook[sheet_name]
        headers = _headers(sheet)
        index = _header_index(sheet)
        for field, spec in table.fields.items():
            if spec.required and field not in headers:
                report.errors.append(ValidationIssue(level="error", table=table_name, field=field, message="required field missing from sheet"))
        seen: set[tuple[Any, ...]] = set()
        for row_idx in range(2, sheet.max_row + 1):
            row = _row_dict(sheet, row_idx)
            if not any(value not in (None, "") for value in row.values()):
                continue
            for field, spec in table.fields.items():
                value = row.get(field)
                if spec.required and value in (None, ""):
                    report.errors.append(ValidationIssue(level="error", table=table_name, row=row_idx, field=field, message="required value missing"))
                if value not in (None, "") and spec.type == "int":
                    try:
                        int(value)
                    except (TypeError, ValueError):
                        report.errors.append(ValidationIssue(level="error", table=table_name, row=row_idx, field=field, message="expected int"))
            if table.primary_key and all(field in index for field in table.primary_key):
                key = tuple(row.get(field) for field in table.primary_key)
                if key in seen:
                    report.errors.append(ValidationIssue(level="error", table=table_name, row=row_idx, message=f"duplicate primary key {key}"))
                seen.add(key)
    return report


def apply_patch(manifest: Manifest, schema: SchemaBundle, patch: Patch, base_dir: Path, run_dir: Path) -> dict[str, Any]:
    states = _open_states(manifest, schema, patch, base_dir, run_dir)
    before: dict[str, dict[str, list[dict[str, Any]]]] = {key: _snapshot(state.workbook) for key, state in states.items()}
    rollback_ops: list[PatchOperation] = []
    operation_results: list[dict[str, Any]] = []

    for operation in patch.operations:
        table = schema.tables[operation.target_table]
        source_path, sheet_name = _table_ref(manifest, schema, operation.target_table, base_dir)
        state = states[str(source_path)]
        sheet = _ensure_sheet(state.workbook, sheet_name, list(table.fields.keys()))

        if operation.op == "update":
            rows = _find_rows(sheet, operation.match)
            old_rows = [_row_dict(sheet, row_idx) for row_idx in rows]
            for row_idx in rows:
                allowed = {
                    field: value
                    for field, value in operation.set.items()
                    if field not in table.block_update_fields and (not table.allow_update_fields or field in table.allow_update_fields)
                }
                _write_row(sheet, row_idx, allowed)
            for old in old_rows:
                rollback_ops.append(
                    PatchOperation(
                        op="update",
                        target_table=operation.target_table,
                        match=operation.match,
                        set=old,
                        source_ref=operation.source_ref,
                        reason=f"rollback for {operation.reason}",
                        confidence=1.0,
                        risk_level="low",
                        needs_confirmation=False,
                    )
                )
            operation_results.append({"op": operation.op, "target_table": operation.target_table, "affected_rows": len(rows)})

        elif operation.op == "insert":
            for row in operation.rows:
                _write_row(sheet, sheet.max_row + 1, row)
                match = {field: row.get(field) for field in table.primary_key if field in row}
                if match:
                    rollback_ops.append(
                        PatchOperation(
                            op="delete_where",
                            target_table=operation.target_table,
                            match=match,
                            source_ref=operation.source_ref,
                            reason=f"rollback insert for {operation.reason}",
                            confidence=1.0,
                            risk_level="low",
                            needs_confirmation=False,
                        )
                    )
            operation_results.append({"op": operation.op, "target_table": operation.target_table, "affected_rows": len(operation.rows)})

        elif operation.op == "delete_where":
            rows = _find_rows(sheet, operation.match)
            old_rows = [_row_dict(sheet, row_idx) for row_idx in rows]
            for row_idx in sorted(rows, reverse=True):
                sheet.delete_rows(row_idx, 1)
            if old_rows:
                rollback_ops.append(
                    PatchOperation(
                        op="insert",
                        target_table=operation.target_table,
                        rows=old_rows,
                        source_ref=operation.source_ref,
                        reason=f"rollback delete for {operation.reason}",
                        confidence=1.0,
                        risk_level="low",
                        needs_confirmation=False,
                    )
                )
            operation_results.append({"op": operation.op, "target_table": operation.target_table, "affected_rows": len(rows)})

        elif operation.op == "replace_group":
            rows = _find_rows(sheet, operation.match)
            old_rows = [_row_dict(sheet, row_idx) for row_idx in rows]
            for row_idx in sorted(rows, reverse=True):
                sheet.delete_rows(row_idx, 1)
            for row in operation.rows:
                _write_row(sheet, sheet.max_row + 1, row)
            rollback_ops.append(
                PatchOperation(
                    op="replace_group",
                    target_table=operation.target_table,
                    match=operation.match,
                    rows=old_rows,
                    source_ref=operation.source_ref,
                    reason=f"rollback replace group for {operation.reason}",
                    confidence=1.0,
                    risk_level="low",
                    needs_confirmation=False,
                )
            )
            operation_results.append({"op": operation.op, "target_table": operation.target_table, "affected_rows": len(rows) + len(operation.rows)})

    previews: dict[str, str] = {}
    validation_reports: dict[str, Any] = {}
    diffs: dict[str, Any] = {}
    for key, state in states.items():
        if state.source_path.exists():
            backup = run_dir / "backups" / state.source_path.name
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(state.source_path, backup)
        state.workbook.save(state.preview_path)
        previews[key] = str(state.preview_path)
        report = _validate_workbook(state.workbook, schema)
        validation_reports[key] = report.model_dump()
        after = _snapshot(state.workbook)
        file_diff: dict[str, Any] = {}
        for table_name, table in schema.tables.items():
            sheet_name = table.sheet or table_name
            if sheet_name in before[key] or sheet_name in after:
                file_diff[sheet_name] = _diff_table(before[key].get(sheet_name, []), after.get(sheet_name, []), table.primary_key)
        diffs[key] = file_diff

    rollback = Patch(
        patch_id=f"rollback_{patch.patch_id}",
        project=patch.project,
        mode=patch.mode,
        operations=list(reversed(rollback_ops)),
        generated_by="ai-meta-agent",
    )
    return {
        "patch_id": patch.patch_id,
        "operation_results": operation_results,
        "previews": previews,
        "diff": diffs,
        "validation": validation_reports,
        "rollback_patch": rollback.model_dump(mode="json", exclude_none=True),
    }
