from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .ai_context import build_minimal_context, summarize_analysis
from .config_discovery import discover_config_tables
from .draft import call_baseai, make_stub_patch
from .habits import append_habit, habit_from_patch, load_habits, match_habits
from .io_utils import make_run_dir, read_json, write_json, write_text
from .models import Manifest, Patch
from .patch_engine import apply_patch
from .schema import load_schema
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


def _habit_path(base_dir: Path, manifest: Manifest) -> Path:
    path = Path(manifest.habit_store)
    if not path.is_absolute():
        path = base_dir / path
    return path


def analyze_manifest(manifest_path: Path, base_dir: Path, label: str = "analysis") -> tuple[Manifest, Any, Path, dict[str, Any]]:
    manifest = _load_manifest(manifest_path)
    schema = load_schema(_schema_path(base_dir, manifest))
    manifest, config_discovery = discover_config_tables(manifest, schema, base_dir)
    run_dir = make_run_dir(_run_root(base_dir, manifest), label)
    workbooks = []
    source_errors = []
    for source in manifest.planning_sources:
        try:
            workbooks.append(load_source_ir(source, base_dir))
        except Exception as exc:  # noqa: BLE001 - surfaced in report for mixed Feishu/local manifests.
            source_errors.append({"source_id": source.id, "kind": source.kind, "message": str(exc)})
    habits = load_habits(_habit_path(base_dir, manifest))
    matched = match_habits(habits, manifest.project, list(schema.tables.keys()))
    context = build_minimal_context(manifest, schema, workbooks, matched)
    context["source_errors"] = source_errors
    context["config_discovery"] = config_discovery
    analysis = {
        "run_dir": str(run_dir),
        "manifest": manifest.model_dump(mode="json"),
        "workbooks": [workbook.model_dump(mode="json", exclude_none=True) for workbook in workbooks],
        "source_errors": source_errors,
        "schema": schema.model_dump(mode="json", exclude_none=True),
        "matched_habits": [habit.model_dump(mode="json", exclude_none=True) for habit in matched],
        "config_discovery": config_discovery,
    }
    write_json(run_dir / "analysis.json", analysis)
    write_json(run_dir / "ai-context.json", context)
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
        patch = call_baseai(manifest, context)
    Patch.model_validate(patch.model_dump())
    write_json(run_dir / "patch.json", patch.model_dump(mode="json", exclude_none=True))
    write_json(run_dir / "candidate-habits.json", _candidate_habits_from_patch(patch))
    write_text(run_dir / "patch.md", _patch_markdown(patch))
    print(json.dumps({"run_dir": str(run_dir), "patch": str(run_dir / "patch.json"), "operations": len(patch.operations)}, ensure_ascii=False, indent=2))
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
    lines = [f"# Apply Result {result['patch_id']}", "", "## Operation Results"]
    for item in result["operation_results"]:
        lines.append(f"- `{item['op']}` `{item['target_table']}` affected={item['affected_rows']}")
    lines.append("")
    lines.append("## Preview Files")
    for source, preview in result["previews"].items():
        lines.append(f"- {source} -> {preview}")
    lines.append("")
    lines.append("## Validation")
    for source, report in result["validation"].items():
        errors = len(report.get("errors", []))
        warnings = len(report.get("warnings", []))
        needs = len(report.get("needs_confirmation", []))
        lines.append(f"- {source}: errors={errors}, warnings={warnings}, needs_confirmation={needs}")
    lines.append("")
    return "\n".join(lines)


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
    manifest, _ = discover_config_tables(manifest, schema, base_dir)
    patch = Patch.model_validate(read_json(patch_path))
    run_dir = make_run_dir(_run_root(base_dir, manifest), "apply")
    result = apply_patch(manifest, schema, patch, base_dir, run_dir)
    write_json(run_dir / "apply-result.json", result)
    write_json(run_dir / "diff.json", result["diff"])
    write_json(run_dir / "validation.json", result["validation"])
    write_json(run_dir / "rollback-patch.json", result["rollback_patch"])
    write_text(run_dir / "apply-result.md", _apply_markdown(result))
    print(json.dumps({"run_dir": str(run_dir), "result": str(run_dir / "apply-result.json")}, ensure_ascii=False, indent=2))
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
    print(json.dumps({"habit_id": habit.habit_id, "store": str(_habit_path(base_dir, manifest))}, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-meta-agent-core")
    parser.add_argument("--base-dir", default=".", help="Base directory for relative manifest paths")
    sub = parser.add_subparsers(dest="command", required=True)

    analyze = sub.add_parser("analyze")
    analyze.add_argument("--manifest", required=True)
    analyze.set_defaults(func=cmd_analyze)

    draft = sub.add_parser("draft")
    draft.add_argument("--manifest", required=True)
    draft.add_argument("--stub", action="store_true")
    draft.add_argument("--context-only", action="store_true")
    draft.set_defaults(func=cmd_draft)

    apply_cmd = sub.add_parser("apply")
    apply_cmd.add_argument("--manifest", required=True)
    apply_cmd.add_argument("--patch", required=True)
    apply_cmd.set_defaults(func=cmd_apply)

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
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
