from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .ai_context import build_minimal_context, summarize_analysis
from .config_discovery import discover_config_tables
from .configuration_records import (
    build_configuration_record,
    local_case_review,
    persist_configuration_record,
    save_case_review,
)
from .draft import (
    call_baseai,
    call_case_review_ai,
    call_draft_diagnostics_ai,
    call_experience_summary_ai,
    call_relationship_ai,
    make_stub_patch,
)
from .draft_diagnostics import (
    build_draft_diagnostics,
    compact_draft_diagnostic_context,
    extract_ai_reasoning,
)
from .experience import (
    append_case_from_patch,
    build_experience_context,
    delete_saved_experience,
    experience_context_payload,
    list_saved_experiences,
    merge_experience_summary,
    summarize_experience_locally,
    teach_experience,
    update_saved_experience,
)
from .habits import append_habit, habit_from_patch, load_habits, match_habits
from .io_utils import make_run_dir, read_json, write_json, write_text
from .item_resolution import compact_item_resolution, resolve_planning_items
from .models import Manifest, Patch
from .patch_engine import apply_patch
from .relation_scanner import compact_relationship_context, scan_relationships
from .schema import load_schema
from .schema_scanner import scan_config_schema
from .workbook_ir import load_source_ir


def _load_manifest(path: Path) -> Manifest:
    return Manifest.model_validate(read_json(path))


def _run_root(base_dir: Path, manifest: Manifest) -> Path:
    root = Path(manifest.run_root)
    if not root.is_absolute():
        root = base_dir / root
    root.mkdir(parents=True, exist_ok=True)
    return root


def _schema_path(base_dir: Path, manifest: Manifest) -> Path:
    path = Path(manifest.schema_path)
    if not path.is_absolute():
        path = base_dir / path
    return path


def _schema_scan_report_path(base_dir: Path, manifest: Manifest) -> Path | None:
    schema_path = _schema_path(base_dir, manifest)
    sibling = schema_path.with_name("schema-scan.json")
    if sibling.exists():
        return sibling
    run_root = Path(manifest.run_root)
    if not run_root.is_absolute():
        run_root = base_dir / run_root
    pointer = run_root / "LATEST_SCHEMA_SCAN.txt"
    if pointer.exists():
        value = pointer.read_text(encoding="utf-8").strip()
        if value:
            candidate = Path(value) / "schema-scan.json"
            if candidate.exists():
                return candidate
    return None


def _habit_path(base_dir: Path, manifest: Manifest) -> Path:
    path = Path(manifest.habit_store)
    if not path.is_absolute():
        path = base_dir / path
    return path


def _targeted_schema(schema: Any, manifest: Manifest) -> Any:
    if not manifest.target_tables:
        return schema
    selected = {name: schema.tables[name] for name in manifest.target_tables if name in schema.tables}
    if not selected:
        available = ", ".join(sorted(schema.tables.keys())[:20])
        raise ValueError(f"Target table(s) not found in schema: {', '.join(manifest.target_tables)}. Available examples: {available}")
    schema = schema.model_copy(deep=True)
    schema.tables = selected
    return schema


def _schema_for_tables(schema: Any, table_names: list[str]) -> Any:
    selected = {name: schema.tables[name] for name in table_names if name in schema.tables}
    schema = schema.model_copy(deep=True)
    schema.tables = selected
    return schema


def _ordered_unique(values: list[str]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        name = str(value or "").strip()
        if name and name not in seen:
            seen.add(name)
            result.append(name)
    return result


def _auto_expand_generation_tables(manifest: Manifest, full_schema: Any, config_plan: dict[str, Any]) -> tuple[list[str], list[str]]:
    if not manifest.target_tables:
        return list(full_schema.tables.keys()), []
    selected = [name for name in manifest.target_tables if name in full_schema.tables]
    recommended = _ordered_unique(
        [
            *selected,
            *config_plan.get("relation_chain", []),
            *list((config_plan.get("required_fields") or {}).keys()),
            *(config_plan.get("recommended_target_tables") or [])[:4],
        ]
    )
    available = [name for name in recommended if name in full_schema.tables]
    extra = [name for name in available if name not in selected]
    # Keep expansion focused: these tables are only added when the activity
    # template or relation scan named them, and every generated operation still
    # goes through preview/validation before any overwrite is possible.
    limited = [*selected, *extra[:8]]
    return limited, [name for name in limited if name not in selected]


def analyze_manifest(manifest_path: Path, base_dir: Path, label: str = "analysis") -> tuple[Manifest, Any, Path, dict[str, Any]]:
    manifest = _load_manifest(manifest_path)
    full_schema = load_schema(_schema_path(base_dir, manifest))
    schema = _targeted_schema(full_schema, manifest)
    manifest, config_discovery = discover_config_tables(manifest, schema, base_dir)
    run_dir = make_run_dir(_run_root(base_dir, manifest), label)
    relationship_map = scan_relationships(manifest, full_schema, base_dir, run_dir, _schema_scan_report_path(base_dir, manifest))
    workbooks = []
    source_errors = []
    for source in manifest.planning_sources:
        try:
            workbooks.append(load_source_ir(source, base_dir))
        except Exception as exc:  # noqa: BLE001 - surfaced in report for mixed Feishu/local manifests.
            source_errors.append({"source_id": source.id, "kind": source.kind, "message": str(exc)})
    habits = load_habits(_habit_path(base_dir, manifest))
    matched = match_habits(habits, manifest.project, list(schema.tables.keys()))
    experience = build_experience_context(base_dir, manifest, schema, workbooks, relationship_map)
    auto_tables, auto_included_tables = _auto_expand_generation_tables(manifest, full_schema, experience["config_plan"])
    if auto_included_tables:
        schema = _schema_for_tables(full_schema, auto_tables)
        manifest = manifest.model_copy(update={"target_tables": auto_tables}, deep=True)
        manifest, config_discovery = discover_config_tables(manifest, schema, base_dir)
        relationship_map = scan_relationships(manifest, full_schema, base_dir, run_dir, _schema_scan_report_path(base_dir, manifest))
        matched = match_habits(habits, manifest.project, list(schema.tables.keys()))
        experience = build_experience_context(base_dir, manifest, schema, workbooks, relationship_map)
        experience["config_plan"]["auto_included_target_tables"] = auto_included_tables
    else:
        auto_included_tables = []
    item_resolution = resolve_planning_items(manifest, workbooks)
    compact_items = compact_item_resolution(item_resolution)
    context = build_minimal_context(manifest, schema, workbooks, matched, experience_context_payload(experience), compact_items)
    context["source_errors"] = source_errors
    context["config_discovery"] = config_discovery
    context["relationship_map"] = compact_relationship_context(relationship_map)
    context["auto_included_target_tables"] = auto_included_tables
    analysis = {
        "run_dir": str(run_dir),
        "manifest": manifest.model_dump(mode="json"),
        "workbooks": [workbook.model_dump(mode="json", exclude_none=True) for workbook in workbooks],
        "source_errors": source_errors,
        "schema": schema.model_dump(mode="json", exclude_none=True),
        "matched_habits": [habit.model_dump(mode="json", exclude_none=True) for habit in matched],
        "config_discovery": config_discovery,
        "relationship_map": relationship_map,
        "planning_item_resolution": item_resolution,
        "experience": experience,
        "config_plan": experience["config_plan"],
        "auto_included_target_tables": auto_included_tables,
    }
    write_json(run_dir / "analysis.json", analysis)
    write_json(run_dir / "ai-context.json", context)
    write_json(run_dir / "config-plan.json", experience["config_plan"])
    write_json(run_dir / "planning-item-resolution.json", item_resolution)
    write_text(run_dir / "analysis.md", summarize_analysis(workbooks, schema, matched))
    return manifest, schema, run_dir, context


def cmd_analyze(args: argparse.Namespace) -> int:
    base_dir = Path(args.base_dir).resolve()
    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = base_dir / manifest_path
    _, _, run_dir, analysis_context = analyze_manifest(manifest_path, base_dir, "analysis")
    output = {"run_dir": str(run_dir), "source_errors": analysis_context.get("source_errors", [])}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def cmd_teach(args: argparse.Namespace) -> int:
    base_dir = Path(args.base_dir).resolve()
    project = args.project
    if args.manifest:
        manifest_path = Path(args.manifest)
        if not manifest_path.is_absolute():
            manifest_path = base_dir / manifest_path
        project = _load_manifest(manifest_path).project
    result = teach_experience(base_dir, project, args.text, source=args.source)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_experience_summary(args: argparse.Namespace) -> int:
    base_dir = Path(args.base_dir).resolve()
    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = base_dir / manifest_path
    manifest = _load_manifest(manifest_path)
    run_dir = make_run_dir(_run_root(base_dir, manifest), "experience-summary")
    local_summary = summarize_experience_locally(manifest.project, args.text)
    ai_summary = None
    ai_error = None
    if not args.no_ai:
        try:
            schema_tables: list[str] = []
            try:
                schema = load_schema(_schema_path(base_dir, manifest))
                schema_tables = sorted(schema.tables.keys())[:300]
            except Exception:
                schema_tables = []
            ai_summary = call_experience_summary_ai(
                manifest,
                {
                    "project": manifest.project,
                    "raw_experience": args.text,
                    "target_tables": manifest.target_tables,
                    "schema_tables": schema_tables,
                    "local_parse": local_summary.get("records_preview", {}),
                    "instruction": "整理成用户确认后可保存的配表经验，不要生成 patch，不要写表。",
                },
                run_dir / "experience-summary-ai-response.json",
            )
        except Exception as exc:  # noqa: BLE001 - local summary keeps the teaching flow usable without AI.
            ai_error = str(exc)
    summary = merge_experience_summary(manifest.project, args.text, local_summary, ai_summary, ai_error)
    write_json(run_dir / "experience-summary.json", summary)
    print(
        json.dumps(
            {
                "run_dir": str(run_dir),
                "experience_summary": str(run_dir / "experience-summary.json"),
                "mode": summary["mode"],
                "summary_title": summary["summary_title"],
                "question_count": len(summary.get("questions", [])),
                "ai_error": summary.get("ai_error"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_experience_list(args: argparse.Namespace) -> int:
    base_dir = Path(args.base_dir).resolve()
    project = args.project
    if args.manifest:
        manifest_path = Path(args.manifest)
        if not manifest_path.is_absolute():
            manifest_path = base_dir / manifest_path
        project = _load_manifest(manifest_path).project
    result = list_saved_experiences(base_dir, project=project)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_experience_update(args: argparse.Namespace) -> int:
    base_dir = Path(args.base_dir).resolve()
    project = args.project
    if args.manifest:
        manifest_path = Path(args.manifest)
        if not manifest_path.is_absolute():
            manifest_path = base_dir / manifest_path
        project = _load_manifest(manifest_path).project
    result = update_saved_experience(base_dir, args.experience_id, args.text, project=project, source=args.source)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_experience_delete(args: argparse.Namespace) -> int:
    base_dir = Path(args.base_dir).resolve()
    result = delete_saved_experience(base_dir, args.experience_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    base_dir = Path(args.base_dir).resolve()
    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = base_dir / manifest_path
    _, _, run_dir, context = analyze_manifest(manifest_path, base_dir, "config-plan")
    output = {
        "run_dir": str(run_dir),
        "config_plan": str(run_dir / "config-plan.json"),
        "activity_type": context.get("config_plan", {}).get("activity_type"),
        "recommended_target_tables": context.get("config_plan", {}).get("recommended_target_tables", []),
        "pending_confirmations": len(context.get("config_plan", {}).get("pending_confirmations", [])),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def cmd_schema_scan(args: argparse.Namespace) -> int:
    base_dir = Path(args.base_dir).resolve()
    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = base_dir / manifest_path
    manifest = _load_manifest(manifest_path)
    run_dir = make_run_dir(_run_root(base_dir, manifest), "schema-scan")
    result = scan_config_schema(manifest, base_dir, run_dir, sample_limit=args.sample_rows)
    write_text(_run_root(base_dir, manifest) / "LATEST_SCHEMA_SCAN.txt", str(run_dir.resolve()))
    write_text(_run_root(base_dir, manifest) / "LATEST_SCHEMA_DRAFT.txt", str((run_dir / "schema-draft.json").resolve()))
    print(
        json.dumps(
            {
                "run_dir": str(run_dir),
                "schema_draft": str(run_dir / "schema-draft.json"),
                "report": str(run_dir / "schema-scan.json"),
                "table_count": result["report"]["table_count"],
                "skipped_sheets": len(result["report"]["skipped_sheets"]),
                "errors": len(result["report"]["errors"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_relations(args: argparse.Namespace) -> int:
    base_dir = Path(args.base_dir).resolve()
    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = base_dir / manifest_path
    manifest = _load_manifest(manifest_path)
    schema = load_schema(_schema_path(base_dir, manifest))
    run_dir = make_run_dir(_run_root(base_dir, manifest), "relation-scan")
    result = scan_relationships(manifest, schema, base_dir, run_dir, _schema_scan_report_path(base_dir, manifest), max_rows=args.max_rows)
    if args.explain:
        ai_review = call_relationship_ai(manifest, compact_relationship_context(result), run_dir / "relationship-ai-response.json")
        result["ai_review"] = {"mode": "ai", **ai_review}
        write_json(run_dir / "relationship-map.json", result)
    write_text(_run_root(base_dir, manifest) / "LATEST_RELATION_SCAN.txt", str(run_dir.resolve()))
    print(
        json.dumps(
            {
                "run_dir": str(run_dir),
                "relationship_map": str(run_dir / "relationship-map.json"),
                "relation_count": result["summary"]["relation_count"],
                "recommended_tables": result["recommended_tables"],
                "error_count": result["summary"]["error_count"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _candidate_habits_from_patch(patch: Patch) -> list[dict[str, Any]]:
    candidates = []
    for operation in patch.operations:
        candidates.append(
            {
                "name": f"{operation.target_table} {operation.op} preference",
                "scenario": operation.reason,
                "applies_to": {"project": patch.project, "target_table": operation.target_table},
                "action": {
                    "op": operation.op,
                    "risk_level": operation.risk_level,
                    "needs_confirmation": operation.needs_confirmation,
                },
                "confidence": min(operation.confidence, 0.8),
                "source_patch": patch.patch_id,
            }
        )
    return candidates


def cmd_draft(args: argparse.Namespace) -> int:
    base_dir = Path(args.base_dir).resolve()
    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = base_dir / manifest_path
    manifest, schema, run_dir, context = analyze_manifest(manifest_path, base_dir, "draft")
    if args.context_only:
        print(json.dumps({"run_dir": str(run_dir), "context": str(run_dir / "ai-context.json")}, ensure_ascii=False, indent=2))
        return 0
    if args.stub:
        patch = make_stub_patch(manifest, schema, context, str(base_dir))
    else:
        patch = call_baseai(manifest, context, run_dir / "ai-response.json")
    Patch.model_validate(patch.model_dump())
    write_json(run_dir / "patch.json", patch.model_dump(mode="json", exclude_none=True))
    write_json(run_dir / "candidate-habits.json", _candidate_habits_from_patch(patch))
    ai_review = None
    ai_reason = extract_ai_reasoning(run_dir / "ai-response.json")
    if not args.stub and not patch.operations:
        try:
            ai_review = call_draft_diagnostics_ai(
                manifest,
                compact_draft_diagnostic_context(manifest, context, patch),
                run_dir / "draft-diagnostics-ai-response.json",
            )
        except Exception as exc:  # noqa: BLE001 - local diagnostics still explain the empty patch.
            ai_review = {"error": str(exc)}
    diagnostics = build_draft_diagnostics(
        manifest,
        context,
        patch,
        ai_reason=ai_reason,
        ai_review=ai_review,
    )
    write_json(run_dir / "draft-diagnostics.json", diagnostics)
    write_text(run_dir / "patch.md", _patch_markdown(patch))
    print(
        json.dumps(
            {
                "run_dir": str(run_dir),
                "patch": str(run_dir / "patch.json"),
                "draft_diagnostics": str(run_dir / "draft-diagnostics.json"),
                "operations": len(patch.operations),
                "diagnostic_status": diagnostics["status"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _patch_markdown(patch: Patch) -> str:
    lines = [f"# Patch {patch.patch_id}", "", f"Project: `{patch.project}`", "", "## Operations"]
    if not patch.operations:
        lines.append("- No operations")
    for index, operation in enumerate(patch.operations, start=1):
        lines.append(
            f"- {index}. `{operation.op}` `{operation.target_table}` confidence={operation.confidence:.2f} risk={operation.risk_level} confirm={operation.needs_confirmation}"
        )
        lines.append(f"  - reason: {operation.reason}")
    lines.append("")
    return "\n".join(lines)


def _apply_markdown(result: dict[str, Any]) -> str:
    lines = [
        f"# Apply Result {result['patch_id']}",
        "",
        f"- Write mode: `{result.get('write_mode', 'preview')}`",
        "",
        "## Operation Results",
    ]
    for item in result["operation_results"]:
        lines.append(f"- `{item['op']}` `{item['target_table']}` affected={item['affected_rows']}")
    lines.append("")
    lines.append("## Preview Files")
    for source, preview in result["previews"].items():
        lines.append(f"- {source} -> {preview}")
    if result.get("backups"):
        lines.append("")
        lines.append("## Backups")
        for source, backup in result["backups"].items():
            lines.append(f"- {source} -> {backup}")
    if result.get("written_files"):
        lines.append("")
        lines.append("## Written Files")
        for source, target in result["written_files"].items():
            lines.append(f"- {source} -> {target}")
    lines.append("")
    lines.append("## Validation")
    for source, report in result["validation"].items():
        errors = len(report.get("errors", []))
        warnings = len(report.get("warnings", []))
        needs = len(report.get("needs_confirmation", []))
        lines.append(f"- {source}: errors={errors}, warnings={warnings}, needs_confirmation={needs}")
    lines.append("")
    return "\n".join(lines)


def _case_review_markdown(case: dict[str, Any], review: dict[str, Any]) -> str:
    lines = [
        f"# 配表案例复盘 {case.get('case_id')}",
        "",
        f"- Project: `{case.get('project')}`",
        f"- Patch: `{case.get('patch_id')}`",
        f"- Write mode: `{case.get('write_mode')}`",
        "",
    ]
    if review.get("summary"):
        lines.extend(["## 总结", str(review["summary"]), ""])
    for title, key in [("问题", "mistakes"), ("经验", "lessons"), ("下次避免", "avoid_next_time")]:
        values = review.get(key) or []
        if not values:
            continue
        lines.append(f"## {title}")
        for value in values:
            lines.append(f"- {value}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def cmd_apply(args: argparse.Namespace) -> int:
    base_dir = Path(args.base_dir).resolve()
    manifest_path = Path(args.manifest)
    patch_path = Path(args.patch)
    if not manifest_path.is_absolute():
        manifest_path = base_dir / manifest_path
    if not patch_path.is_absolute():
        patch_path = base_dir / patch_path
    manifest = _load_manifest(manifest_path)
    schema = load_schema(_schema_path(base_dir, manifest))
    schema = _targeted_schema(schema, manifest)
    manifest, _ = discover_config_tables(manifest, schema, base_dir)
    patch = Patch.model_validate(read_json(patch_path))
    run_dir = make_run_dir(_run_root(base_dir, manifest), "apply")
    result = apply_patch(manifest, schema, patch, base_dir, run_dir, write_mode=args.write_mode)
    record = build_configuration_record(manifest, patch, result, run_dir)
    result["configuration_record"] = record
    result["configuration_record_paths"] = persist_configuration_record(base_dir, record, run_dir)
    write_json(run_dir / "apply-result.json", result)
    write_json(run_dir / "diff.json", result["diff"])
    write_json(run_dir / "validation.json", result["validation"])
    write_json(run_dir / "rollback-patch.json", result["rollback_patch"])
    write_text(run_dir / "apply-result.md", _apply_markdown(result))
    print(
        json.dumps(
            {
                "run_dir": str(run_dir),
                "result": str(run_dir / "apply-result.json"),
                "configuration_record": str(run_dir / "configuration-record.json"),
                "write_mode": args.write_mode,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_case_review(args: argparse.Namespace) -> int:
    base_dir = Path(args.base_dir).resolve()
    manifest_path = Path(args.manifest)
    patch_path = Path(args.patch)
    apply_result_path = Path(args.apply_result)
    if not manifest_path.is_absolute():
        manifest_path = base_dir / manifest_path
    if not patch_path.is_absolute():
        patch_path = base_dir / patch_path
    if not apply_result_path.is_absolute():
        apply_result_path = base_dir / apply_result_path
    correction_text = args.correction.strip()
    if not correction_text:
        raise ValueError("请先填写本次配表的问题或修正建议。")

    manifest = _load_manifest(manifest_path)
    patch = Patch.model_validate(read_json(patch_path))
    apply_result = read_json(apply_result_path)
    run_dir = apply_result_path.parent
    record = apply_result.get("configuration_record") or build_configuration_record(manifest, patch, apply_result, run_dir)
    local_review = local_case_review(correction_text, record)
    ai_review = None
    ai_error = None
    if not args.no_ai:
        try:
            ai_review = call_case_review_ai(
                manifest,
                {
                    "project": manifest.project,
                    "correction_text": correction_text,
                    "configuration_record": record,
                    "validation_summary": record.get("validation_summary", {}),
                },
                run_dir / "case-review-ai-response.json",
            )
        except Exception as exc:  # noqa: BLE001 - local review still keeps the learning loop usable.
            ai_error = str(exc)
    review = ai_review or local_review
    review.setdefault("summary", local_review.get("summary"))
    review.setdefault("mistakes", local_review.get("mistakes", []))
    review.setdefault("lessons", local_review.get("lessons", []))
    review.setdefault("avoid_next_time", local_review.get("avoid_next_time", []))
    review.setdefault("affected_tables", record.get("target_tables", []))
    review["mode"] = "ai" if ai_review else "local"
    if ai_error:
        review["ai_error"] = ai_error

    case = save_case_review(base_dir, manifest, patch, apply_result, correction_text, review)
    payload = {"case": case, "case_review": review, "configuration_record": record}
    write_json(run_dir / "case-review.json", payload)
    write_text(run_dir / "case-review.md", _case_review_markdown(case, review))
    print(
        json.dumps(
            {
                "run_dir": str(run_dir),
                "case_review": str(run_dir / "case-review.json"),
                "case_id": case["case_id"],
                "mode": review["mode"],
                "ai_error": ai_error,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_learn(args: argparse.Namespace) -> int:
    base_dir = Path(args.base_dir).resolve()
    manifest_path = Path(args.manifest)
    patch_path = Path(args.patch)
    if not manifest_path.is_absolute():
        manifest_path = base_dir / manifest_path
    if not patch_path.is_absolute():
        patch_path = base_dir / patch_path
    manifest = _load_manifest(manifest_path)
    patch = Patch.model_validate(read_json(patch_path))
    habit = habit_from_patch(patch, args.decision, args.note)
    append_habit(_habit_path(base_dir, manifest), habit)
    case = append_case_from_patch(base_dir, manifest, patch, args.decision, args.note)
    print(
        json.dumps(
            {
                "habit_id": habit.habit_id,
                "case_id": case["case_id"],
                "store": str(_habit_path(base_dir, manifest)),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-meta-agent-core")
    parser.add_argument("--base-dir", default=".", help="Base directory for relative manifest paths")
    sub = parser.add_subparsers(dest="command", required=True)

    analyze = sub.add_parser("analyze")
    analyze.add_argument("--manifest", required=True)
    analyze.set_defaults(func=cmd_analyze)

    teach = sub.add_parser("teach")
    teach.add_argument("--manifest", default=None)
    teach.add_argument("--project", default="default")
    teach.add_argument("--text", required=True)
    teach.add_argument("--source", default="manual")
    teach.set_defaults(func=cmd_teach)

    experience_summary = sub.add_parser("experience-summary")
    experience_summary.add_argument("--manifest", required=True)
    experience_summary.add_argument("--text", required=True)
    experience_summary.add_argument("--no-ai", action="store_true")
    experience_summary.set_defaults(func=cmd_experience_summary)

    experience_list = sub.add_parser("experience-list")
    experience_list.add_argument("--manifest", default=None)
    experience_list.add_argument("--project", default=None)
    experience_list.set_defaults(func=cmd_experience_list)

    experience_update = sub.add_parser("experience-update")
    experience_update.add_argument("--manifest", default=None)
    experience_update.add_argument("--project", default=None)
    experience_update.add_argument("--experience-id", required=True)
    experience_update.add_argument("--text", required=True)
    experience_update.add_argument("--source", default="panel")
    experience_update.set_defaults(func=cmd_experience_update)

    experience_delete = sub.add_parser("experience-delete")
    experience_delete.add_argument("--experience-id", required=True)
    experience_delete.set_defaults(func=cmd_experience_delete)

    plan = sub.add_parser("plan")
    plan.add_argument("--manifest", required=True)
    plan.set_defaults(func=cmd_plan)

    schema_scan = sub.add_parser("schema-scan")
    schema_scan.add_argument("--manifest", required=True)
    schema_scan.add_argument("--sample-rows", type=int, default=5)
    schema_scan.set_defaults(func=cmd_schema_scan)

    relations = sub.add_parser("relations")
    relations.add_argument("--manifest", required=True)
    relations.add_argument("--max-rows", type=int, default=1500)
    relations.add_argument("--explain", action="store_true")
    relations.set_defaults(func=cmd_relations)

    draft = sub.add_parser("draft")
    draft.add_argument("--manifest", required=True)
    draft.add_argument("--stub", action="store_true")
    draft.add_argument("--context-only", action="store_true")
    draft.set_defaults(func=cmd_draft)

    apply_cmd = sub.add_parser("apply")
    apply_cmd.add_argument("--manifest", required=True)
    apply_cmd.add_argument("--patch", required=True)
    apply_cmd.add_argument("--write-mode", choices=["preview", "overwrite"], default="preview")
    apply_cmd.set_defaults(func=cmd_apply)

    case_review = sub.add_parser("case-review")
    case_review.add_argument("--manifest", required=True)
    case_review.add_argument("--patch", required=True)
    case_review.add_argument("--apply-result", required=True)
    case_review.add_argument("--correction", required=True)
    case_review.add_argument("--no-ai", action="store_true")
    case_review.set_defaults(func=cmd_case_review)

    learn = sub.add_parser("learn")
    learn.add_argument("--manifest", required=True)
    learn.add_argument("--patch", required=True)
    learn.add_argument("--decision", choices=["accepted", "corrected", "rejected"], default="accepted")
    learn.add_argument("--note", default=None)
    learn.set_defaults(func=cmd_learn)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
