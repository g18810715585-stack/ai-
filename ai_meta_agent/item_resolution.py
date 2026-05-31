from __future__ import annotations

from collections import defaultdict
from typing import Any

from .models import Manifest, WorkbookIR


ITEM_BASE_ROLES = {"item_base", "value_table", "value"}
PLANNING_ROLES = {"planning", ""}

FIELD_ALIASES = {
    "product_name": [
        "商品",
        "商品名",
        "商品名称",
        "道具",
        "道具名",
        "道具名称",
        "项目",
        "名称",
        "奖励",
        "奖励名称",
        "name",
        "product",
        "item",
    ],
    "reward_type": ["奖励类型", "奖励类型1", "type_1", "type1", "type"],
    "content_id": ["内容", "内容id", "内容ID", "奖励内容", "道具id", "道具ID", "id", "reward_1", "content_id"],
    "num": ["数量", "奖励数量", "道具数量", "num_1", "num", "count"],
    "remark": ["备注", "策划备注", "说明", "comment", "note"],
}


def resolve_planning_items(manifest: Manifest, workbooks: list[WorkbookIR], limit: int = 300) -> dict[str, Any]:
    role_by_source = {source.id: source.role for source in manifest.planning_sources}
    configured_item_base_sources = sum(1 for source in manifest.planning_sources if source.role in ITEM_BASE_ROLES)
    planning_workbooks = [workbook for workbook in workbooks if role_by_source.get(workbook.source_id, "planning") in PLANNING_ROLES]
    item_base_workbooks = [workbook for workbook in workbooks if role_by_source.get(workbook.source_id) in ITEM_BASE_ROLES]

    result: dict[str, Any] = {
        "enabled": bool(item_base_workbooks),
        "summary": {
            "planning_sources": len(planning_workbooks),
            "item_base_sources": len(item_base_workbooks),
            "configured_item_base_sources": configured_item_base_sources,
            "indexed_items": 0,
            "matched": 0,
            "missing": 0,
            "direct_rewards": 0,
            "duplicates": 0,
        },
        "matches": [],
        "missing": [],
        "duplicates": [],
        "warnings": [],
    }
    if not item_base_workbooks:
        if configured_item_base_sources:
            result["warnings"].append("价值表来源已配置但没有成功读取，请查看 source_errors 中的飞书授权或网络错误。")
        else:
            result["warnings"].append("未填写价值表飞书链接，无法按商品名补充奖励类型和内容ID。")
        return result

    index, duplicates, ignored = _build_item_base_index(item_base_workbooks)
    result["summary"]["indexed_items"] = len(index)
    result["summary"]["duplicates"] = len(duplicates)
    result["duplicates"] = duplicates[:40]
    if ignored:
        result["warnings"].append(f"价值表中 {ignored} 行缺少商品名、奖励类型或内容ID，已忽略。")

    for workbook in planning_workbooks:
        for sheet in workbook.sheets:
            for row in sheet.sample_rows:
                product_name = _text(_pick(row, "product_name"))
                if not product_name or _is_non_product_name(product_name):
                    continue
                direct = _direct_reward(row)
                if direct:
                    result["summary"]["direct_rewards"] += 1
                    if len(result["matches"]) < limit:
                        result["matches"].append(
                            {
                                "product_name": product_name,
                                "reward_type": direct["reward_type"],
                                "content_id": direct["content_id"],
                                "num": direct["num"],
                                "source": "planning_direct",
                                "confidence": 0.92,
                                "planning_ref": _row_ref(workbook, sheet.name, row),
                                "evidence": "规划表本行已经填写奖励类型和内容ID",
                            }
                        )
                    result["summary"]["matched"] += 1
                    continue
                entry = index.get(_lookup_key(product_name))
                if entry:
                    if len(result["matches"]) < limit:
                        result["matches"].append(
                            {
                                "product_name": product_name,
                                "reward_type": entry["reward_type"],
                                "content_id": entry["content_id"],
                                "num": entry["num"],
                                "remark": entry.get("remark"),
                                "source": "item_base",
                                "confidence": 0.86,
                                "planning_ref": _row_ref(workbook, sheet.name, row),
                                "item_base_ref": entry["source_ref"],
                                "evidence": f"商品名命中价值表：{entry['name']}",
                            }
                        )
                    result["summary"]["matched"] += 1
                else:
                    result["summary"]["missing"] += 1
                    if len(result["missing"]) < 80:
                        result["missing"].append(
                            {
                                "product_name": product_name,
                                "planning_ref": _row_ref(workbook, sheet.name, row),
                                "reason": "价值表未找到同名商品，草案中应进入待确认项。",
                            }
                        )

    if result["summary"]["matched"] == 0:
        result["warnings"].append("未从规划表商品名匹配到价值表奖励类型/内容ID，请检查规划表商品列和价值表链接。")
    return result


def compact_item_resolution(resolution: dict[str, Any], match_limit: int = 80, missing_limit: int = 40) -> dict[str, Any]:
    return {
        "enabled": resolution.get("enabled", False),
        "summary": resolution.get("summary", {}),
        "matches": resolution.get("matches", [])[:match_limit],
        "missing": resolution.get("missing", [])[:missing_limit],
        "duplicates": resolution.get("duplicates", [])[:20],
        "warnings": resolution.get("warnings", []),
    }


def _build_item_base_index(workbooks: list[WorkbookIR]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], int]:
    by_name: dict[str, dict[str, Any]] = {}
    duplicate_bucket: dict[str, list[dict[str, Any]]] = defaultdict(list)
    ignored = 0
    for workbook in workbooks:
        for sheet in workbook.sheets:
            for row in sheet.sample_rows:
                name = _text(_pick(row, "product_name"))
                reward_type = _pick(row, "reward_type")
                content_id = _pick(row, "content_id")
                if not name or _is_non_product_name(name) or _is_blank(reward_type) or _is_blank(content_id):
                    ignored += 1
                    continue
                entry = {
                    "name": name,
                    "reward_type": reward_type,
                    "content_id": content_id,
                    "num": _pick(row, "num") or 1,
                    "remark": _text(_pick(row, "remark")) or name,
                    "source_ref": _row_ref(workbook, sheet.name, row),
                }
                key = _lookup_key(name)
                if key in by_name:
                    duplicate_bucket[key].append(entry)
                    continue
                by_name[key] = entry
    duplicates = [
        {
            "product_name": by_name[key]["name"],
            "kept": by_name[key]["source_ref"],
            "duplicates": [item["source_ref"] for item in items],
        }
        for key, items in duplicate_bucket.items()
    ]
    return by_name, duplicates, ignored


def _direct_reward(row: dict[str, Any]) -> dict[str, Any] | None:
    reward_type = _pick(row, "reward_type")
    content_id = _pick(row, "content_id")
    if _is_blank(reward_type) or _is_blank(content_id):
        return None
    return {"reward_type": reward_type, "content_id": content_id, "num": _pick(row, "num") or 1}


def _row_ref(workbook: WorkbookIR, sheet_name: str, row: dict[str, Any]) -> dict[str, Any]:
    return {
        "workbook": workbook.source_id,
        "sheet": sheet_name,
        "row": row.get("__row"),
        "path": workbook.path,
        "url": workbook.url,
    }


def _pick(row: dict[str, Any], field: str) -> Any:
    normalized = {_normalize_header(key): value for key, value in row.items()}
    for alias in FIELD_ALIASES.get(field, [field]):
        value = normalized.get(_normalize_header(alias))
        if not _is_blank(value):
            return value
    return None


def _normalize_header(value: Any) -> str:
    return str(value or "").strip().replace(" ", "").replace("：", "").replace(":", "").lower()


def _lookup_key(value: Any) -> str:
    return str(value or "").strip().lower()


def _text(value: Any) -> str:
    return "" if _is_blank(value) else str(value).strip()


def _is_blank(value: Any) -> bool:
    return value is None or str(value).strip() == ""


def _is_non_product_name(name: str) -> bool:
    return _lookup_key(name) in {"项目", "商品", "商品名", "商品名称", "合计", "总计", "小计"}
