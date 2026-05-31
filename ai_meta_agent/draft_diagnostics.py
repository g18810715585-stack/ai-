from __future__ import annotations

from pathlib import Path
from typing import Any

from .io_utils import read_json
from .models import Manifest, Patch


REFERENCE_HINTS = (
    "id",
    "group",
    "reward",
    "goods",
    "key",
    "time",
    "title",
    "name",
    "desc",
    "list",
    "form",
    "活动",
    "奖励",
    "商品",
    "文案",
    "标题",
    "时间",
    "组",
)


def extract_ai_reasoning(raw_response_path: Path) -> str | None:
    if not raw_response_path.exists():
        return None
    try:
        payload = read_json(raw_response_path)
        message = payload["response"]["choices"][0]["message"]
    except Exception:  # noqa: BLE001 - diagnostics should never break draft generation.
        return None
    reason = message.get("reasoning_content") or message.get("reason") or ""
    reason = str(reason).strip()
    return reason[:2000] if reason else None


def compact_draft_diagnostic_context(manifest: Manifest, context: dict[str, Any], patch: Patch) -> dict[str, Any]:
    return {
        "project": manifest.project,
        "mode": manifest.mode,
        "patch": {
            "patch_id": patch.patch_id,
            "operation_count": len(patch.operations),
        },
        "target_tables": context.get("target_tables", []),
        "workbooks": [_compact_workbook(workbook) for workbook in context.get("workbooks", [])],
        "schema_tables": {
            table_name: {
                "primary_key": table.get("primary_key", []),
                "fields": list((table.get("fields") or {}).keys())[:80],
                "allow_update_fields": table.get("allow_update_fields", [])[:80],
            }
            for table_name, table in (context.get("schema", {}).get("tables") or {}).items()
        },
        "relationship_map": _compact_relationship_map(context.get("relationship_map") or {}),
        "config_plan": context.get("config_plan", {}),
        "auto_included_target_tables": context.get("auto_included_target_tables", []),
        "source_errors": context.get("source_errors", []),
    }


def build_draft_diagnostics(
    manifest: Manifest,
    context: dict[str, Any],
    patch: Patch,
    *,
    ai_reason: str | None = None,
    ai_review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if patch.operations:
        return {
            "status": "ready",
            "summary": f"已生成 {len(patch.operations)} 个可审核配置变更。",
            "operation_count": len(patch.operations),
            "reasons": [],
            "missing_information": [],
            "suggested_target_tables": [],
            "suggested_field_mappings": [],
            "next_steps": ["检查 Patch 内容，确认后再生成预览。"],
            "ai_reason": ai_reason,
            "ai_review": ai_review,
        }

    relation_map = context.get("relationship_map") or {}
    config_plan = context.get("config_plan") or {}
    target_tables = context.get("target_tables", [])
    auto_included = context.get("auto_included_target_tables", [])
    recommended = [name for name in relation_map.get("recommended_tables", []) if name not in target_tables]
    if auto_included:
        reasons_auto = f"auto included related target tables for this draft: {', '.join(auto_included)}"
    else:
        reasons_auto = ""
    schema_tables = context.get("schema", {}).get("tables") or {}
    workbooks = context.get("workbooks") or []

    reasons = []
    if not workbooks:
        reasons.append("没有成功读取到规划表内容。")
    else:
        reasons.append("AI 没有找到足够安全的规划字段到配置表字段映射。")
    if context.get("source_errors"):
        reasons.append("部分规划来源读取失败，草案生成只使用了已成功读取的内容。")
    if _direct_header_match_count(workbooks, schema_tables) < 2:
        reasons.append("规划表表头与目标配置表字段缺少直接重名或明显对应关系。")
    if recommended:
        reasons.append("已分析到关联表，但这些表尚未全部作为本次生成草案的目标表。")

    if reasons_auto:
        reasons.append(reasons_auto)

    missing = [
        "每条需要新增或修改配置的唯一 ID / 主键 / 可匹配条件。",
        "规划表列名到配置表字段名的对应关系。",
        "哪些表需要新增行，哪些表只是引用已有 ID。",
        "活动时间、活动类型、form/group/reward/goods/key 等关键索引字段的明确取值。",
    ]
    if recommended:
        missing.append("是否把推荐关联表纳入本次草案生成范围。")
    if config_plan.get("missing_information"):
        missing.extend(config_plan["missing_information"])

    return {
        "status": "empty",
        "summary": "本次生成草案没有产生配置变更，工具按安全策略没有写入任何操作。",
        "operation_count": 0,
        "reasons": reasons,
        "missing_information": missing,
        "suggested_target_tables": recommended[:20],
        "suggested_field_mappings": _suggest_field_mappings(schema_tables),
        "auto_included_target_tables": auto_included,
        "planning_overview": [_compact_workbook(workbook) for workbook in workbooks],
        "relationship_summary": {
            "relation_count": relation_map.get("summary", {}).get("relation_count", 0),
            "high_confidence_count": relation_map.get("summary", {}).get("high_confidence_count", 0),
            "recommended_tables": relation_map.get("recommended_tables", [])[:20],
        },
        "config_plan": config_plan,
        "next_steps": [
            "先把推荐关联表中本次活动会实际写入的表勾选进目标配置表。",
            "在飞书规划里补一段字段映射说明，例如：活动 ID -> activity.id，商品组 -> active_shop.group，奖励 -> reward.id。",
            "如果规划表是道具清单或价格表，请标明每一列对应 exchange / reward / goods 的哪个字段。",
            "补完映射后重新点击生成草案。",
        ],
        "ai_reason": ai_reason,
        "ai_review": ai_review,
    }


def _compact_workbook(workbook: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": workbook.get("source_id"),
        "source_type": workbook.get("source_type"),
        "sheets": [
            {
                "name": sheet.get("name"),
                "max_row": sheet.get("max_row"),
                "max_column": sheet.get("max_column"),
                "header_row": sheet.get("header_row"),
                "headers": [header for header in (sheet.get("headers") or []) if header][:40],
                "sample_rows": (sheet.get("sample_rows") or [])[:3],
            }
            for sheet in (workbook.get("sheets") or [])[:5]
        ],
    }


def _compact_relationship_map(relationship_map: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": relationship_map.get("summary", {}),
        "recommended_tables": relationship_map.get("recommended_tables", [])[:20],
        "relations": [
            {
                "from_table": relation.get("from_table"),
                "from_field": relation.get("from_field"),
                "to_table": relation.get("to_table"),
                "to_field": relation.get("to_field"),
                "relation_type": relation.get("relation_type"),
                "confidence": relation.get("confidence"),
            }
            for relation in (relationship_map.get("relations") or [])[:40]
        ],
    }


def _direct_header_match_count(workbooks: list[dict[str, Any]], schema_tables: dict[str, Any]) -> int:
    headers = {
        str(header).strip().lower()
        for workbook in workbooks
        for sheet in workbook.get("sheets", [])
        for header in sheet.get("headers", [])
        if str(header).strip()
    }
    fields = {
        str(field).strip().lower()
        for table in schema_tables.values()
        for field in (table.get("fields") or {})
    }
    return len(headers & fields)


def _suggest_field_mappings(schema_tables: dict[str, Any]) -> list[dict[str, Any]]:
    suggestions = []
    for table_name, table in schema_tables.items():
        fields = list((table.get("fields") or {}).keys())
        important = []
        for field in [*table.get("primary_key", []), *fields]:
            text = str(field).lower()
            if field not in important and any(hint in text for hint in REFERENCE_HINTS):
                important.append(field)
            if len(important) >= 16:
                break
        if not important:
            important = fields[:12]
        suggestions.append(
            {
                "target_table": table_name,
                "primary_key": table.get("primary_key", []),
                "fields_to_map_first": important,
            }
        )
    return suggestions
