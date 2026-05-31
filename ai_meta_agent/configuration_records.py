from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .experience import knowledge_dir
from .io_utils import write_json, write_text
from .models import Manifest, Patch


CONFIG_RECORD_FILE = "configuration_runs.jsonl"
CASE_FILE = "case_examples.jsonl"


def build_configuration_record(manifest: Manifest, patch: Patch, apply_result: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    now = _now()
    op_results = apply_result.get("operation_results", [])
    tables: dict[str, dict[str, Any]] = {}
    for index, operation in enumerate(patch.operations):
        result = op_results[index] if index < len(op_results) else {}
        table = tables.setdefault(
            operation.target_table,
            {
                "table": operation.target_table,
                "operation_count": 0,
                "affected_rows": 0,
                "operations": [],
            },
        )
        table["operation_count"] += 1
        table["affected_rows"] += int(result.get("affected_rows") or 0)
        table["operations"].append(
            {
                "op": operation.op,
                "match": operation.match,
                "set": operation.set,
                "rows": operation.rows[:5],
                "row_count": len(operation.rows),
                "reason": operation.reason,
                "confidence": operation.confidence,
                "risk_level": operation.risk_level,
                "needs_confirmation": operation.needs_confirmation,
                "source_ref": operation.source_ref.model_dump(mode="json", exclude_none=True),
                "affected_rows": result.get("affected_rows", 0),
            }
        )
    record = {
        "record_id": _stable_id("config-record", manifest.project, patch.patch_id, now),
        "project": manifest.project,
        "patch_id": patch.patch_id,
        "created_at": now,
        "run_dir": str(run_dir),
        "write_mode": apply_result.get("write_mode", "preview"),
        "target_tables": list(tables.keys()),
        "operation_count": len(patch.operations),
        "tables": list(tables.values()),
        "previews": apply_result.get("previews", {}),
        "backups": apply_result.get("backups", {}),
        "written_files": apply_result.get("written_files", {}),
        "validation_summary": _validation_summary(apply_result.get("validation", {})),
    }
    return record


def persist_configuration_record(base_dir: Path, record: dict[str, Any], run_dir: Path) -> dict[str, str]:
    root = knowledge_dir(base_dir)
    root.mkdir(parents=True, exist_ok=True)
    _append_jsonl(root / CONFIG_RECORD_FILE, record)
    json_path = run_dir / "configuration-record.json"
    md_path = run_dir / "configuration-record.md"
    write_json(json_path, record)
    write_text(md_path, configuration_record_markdown(record))
    return {"json": str(json_path), "markdown": str(md_path), "store": str(root / CONFIG_RECORD_FILE)}


def configuration_record_markdown(record: dict[str, Any]) -> str:
    lines = [
        f"# 配表记录 {record.get('record_id')}",
        "",
        f"- 项目：`{record.get('project')}`",
        f"- Patch：`{record.get('patch_id')}`",
        f"- 写入方式：`{record.get('write_mode')}`",
        f"- 运行目录：`{record.get('run_dir')}`",
        "",
        "## 表格变更",
    ]
    for table in record.get("tables", []):
        lines.append(f"### {table.get('table')}")
        lines.append(f"- 操作数：{table.get('operation_count')}，影响行：{table.get('affected_rows')}")
        for item in table.get("operations", []):
            fields = ", ".join(item.get("set", {}).keys()) or f"{item.get('row_count', 0)} 行"
            lines.append(f"- `{item.get('op')}` {fields}，置信度 {item.get('confidence')}，风险 {item.get('risk_level')}")
            lines.append(f"  - 原因：{item.get('reason')}")
    lines.extend(["", "## 文件"])
    for source, backup in (record.get("backups") or {}).items():
        lines.append(f"- 备份：`{source}` -> `{backup}`")
    for source, preview in (record.get("previews") or {}).items():
        lines.append(f"- 预览：`{source}` -> `{preview}`")
    for source, target in (record.get("written_files") or {}).items():
        lines.append(f"- 已覆盖：`{source}` -> `{target}`")
    return "\n".join(lines).strip() + "\n"


def local_case_review(correction_text: str, record: dict[str, Any]) -> dict[str, Any]:
    tables = record.get("target_tables", [])
    return {
        "summary": "已记录本次配表问题，后续相似活动会把这条修正案例作为强参考。",
        "mistakes": _split_notes(correction_text),
        "lessons": [
            "生成草案时优先检查历史修正案例。",
            "低置信字段和用户指出的问题类型应进入待确认项。",
            "相同目标表再次出现时，要复核本次修正中提到的字段和关联关系。",
        ],
        "avoid_next_time": _split_notes(correction_text)[:8],
        "affected_tables": tables,
    }


def save_case_review(
    base_dir: Path,
    manifest: Manifest,
    patch: Patch,
    apply_result: dict[str, Any],
    correction_text: str,
    review: dict[str, Any],
) -> dict[str, Any]:
    root = knowledge_dir(base_dir)
    root.mkdir(parents=True, exist_ok=True)
    now = _now()
    case = {
        "case_id": _stable_id("case-review", manifest.project, patch.patch_id, correction_text, now),
        "project": manifest.project,
        "patch_id": patch.patch_id,
        "decision": "corrected",
        "target_tables": _ordered_unique([operation.target_table for operation in patch.operations]),
        "operation_count": len(patch.operations),
        "operation_types": sorted({operation.op for operation in patch.operations}),
        "note": review.get("summary") or correction_text[:160],
        "correction": correction_text,
        "case_review": review,
        "write_mode": apply_result.get("write_mode", "preview"),
        "confidence": 0.88,
        "evidence": [f"{now} corrected via panel"],
        "created_at": now,
    }
    _append_jsonl(root / CASE_FILE, case)
    return case


def _validation_summary(validation: dict[str, Any]) -> dict[str, int]:
    summary = {"errors": 0, "warnings": 0, "needs_confirmation": 0}
    for report in validation.values():
        summary["errors"] += len(report.get("errors", []))
        summary["warnings"] += len(report.get("warnings", []))
        summary["needs_confirmation"] += len(report.get("needs_confirmation", []))
    return summary


def _split_notes(text: str) -> list[str]:
    lines = [line.strip(" -\t") for line in text.splitlines()]
    items = [line for line in lines if line]
    return items or ([text.strip()] if text.strip() else [])


def _append_jsonl(path: Path, item: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")))
        handle.write("\n")


def _stable_id(*parts: Any) -> str:
    raw = "\n".join(str(part) for part in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _ordered_unique(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value and value not in seen:
            result.append(value)
            seen.add(value)
    return result
