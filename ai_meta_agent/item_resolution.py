from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
import re
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


@dataclass(frozen=True)
class ColumnMapping:
    fields: dict[str, str]
    mode: str
    confidence: float
    evidence: list[str]


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
        "candidate_matches": 0,
        "inferred_item_base_sheets": 0,
        },
        "matches": [],
        "missing": [],
        "duplicates": [],
        "column_mappings": [],
        "warnings": [],
    }
    if not item_base_workbooks:
        if configured_item_base_sources:
            result["warnings"].append("价值表来源已配置但没有成功读取，请查看 source_errors 中的飞书授权或网络错误。")
        else:
            result["warnings"].append("未填写价值表飞书链接，无法按商品名补充奖励类型和内容ID。")
        return result

    index, duplicates, ignored, mappings = _build_item_base_index(item_base_workbooks)
    result["summary"]["indexed_items"] = len(index)
    result["summary"]["duplicates"] = len(duplicates)
    result["duplicates"] = duplicates[:40]
    result["column_mappings"] = mappings[:20]
    result["summary"]["inferred_item_base_sheets"] = sum(1 for item in mappings if item.get("mode") != "header_alias")
    if ignored:
        result["warnings"].append(f"价值表中 {ignored} 行缺少商品名、奖励类型或内容ID，已忽略。")

    for workbook in planning_workbooks:
        for sheet in workbook.sheets:
            planning_mapping = _mapping_for_sheet(sheet.sample_rows, allow_inference=True, infer_fields={"product_name"})
            for row in sheet.sample_rows:
                product_name = _text(_pick(row, "product_name", planning_mapping))
                if not product_name or _is_non_product_name(product_name):
                    continue
                direct = _direct_reward(row, planning_mapping)
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
                    candidates = _similar_candidates(product_name, index)
                    if candidates:
                        result["summary"]["candidate_matches"] += 1
                    result["summary"]["missing"] += 1
                    if len(result["missing"]) < 80:
                        result["missing"].append(
                            {
                                "product_name": product_name,
                                "planning_ref": _row_ref(workbook, sheet.name, row),
                                "reason": "价值表未找到同名商品，草案中应进入待确认项。",
                                "candidates": candidates,
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
        "column_mappings": resolution.get("column_mappings", [])[:12],
        "warnings": resolution.get("warnings", []),
    }


def _build_item_base_index(workbooks: list[WorkbookIR]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], int, list[dict[str, Any]]]:
    by_name: dict[str, dict[str, Any]] = {}
    duplicate_bucket: dict[str, list[dict[str, Any]]] = defaultdict(list)
    mappings: list[dict[str, Any]] = []
    ignored = 0
    for workbook in workbooks:
        for sheet in workbook.sheets:
            mapping = _mapping_for_sheet(sheet.sample_rows, allow_inference=True)
            mappings.append(
                {
                    "source_id": workbook.source_id,
                    "sheet": sheet.name,
                    "mode": mapping.mode,
                    "confidence": mapping.confidence,
                    "fields": mapping.fields,
                    "evidence": mapping.evidence,
                }
            )
            for row in sheet.sample_rows:
                name = _text(_pick(row, "product_name", mapping))
                reward_type = _pick(row, "reward_type", mapping)
                content_id = _pick(row, "content_id", mapping)
                if not name or _is_non_product_name(name) or _is_blank(reward_type) or _is_blank(content_id):
                    ignored += 1
                    continue
                entry = {
                    "name": name,
                    "reward_type": reward_type,
                    "content_id": content_id,
                    "num": _pick(row, "num", mapping) or 1,
                    "remark": _text(_pick(row, "remark", mapping)) or name,
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
    return by_name, duplicates, ignored, mappings


def _direct_reward(row: dict[str, Any], mapping: ColumnMapping | None = None) -> dict[str, Any] | None:
    reward_type = _pick(row, "reward_type", mapping)
    content_id = _pick(row, "content_id", mapping)
    if _is_blank(reward_type) or _is_blank(content_id):
        return None
    return {"reward_type": reward_type, "content_id": content_id, "num": _pick(row, "num", mapping) or 1}


def _row_ref(workbook: WorkbookIR, sheet_name: str, row: dict[str, Any]) -> dict[str, Any]:
    return {
        "workbook": workbook.source_id,
        "sheet": sheet_name,
        "row": row.get("__row"),
        "path": workbook.path,
        "url": workbook.url,
    }


def _pick(row: dict[str, Any], field: str, mapping: ColumnMapping | None = None) -> Any:
    if mapping and field in mapping.fields:
        value = row.get(mapping.fields[field])
        if not _is_blank(value):
            return _normalize_cell_value(value)
    normalized = {_normalize_header(key): value for key, value in row.items()}
    for alias in FIELD_ALIASES.get(field, [field]):
        value = normalized.get(_normalize_header(alias))
        if not _is_blank(value):
            return _normalize_cell_value(value)
    return None


def _mapping_for_sheet(rows: list[dict[str, Any]], allow_inference: bool, infer_fields: set[str] | None = None) -> ColumnMapping:
    headers = _headers_from_rows(rows)
    normalized = {_normalize_header(header): header for header in headers}
    fields: dict[str, str] = {}
    evidence: list[str] = []
    for field, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            header = normalized.get(_normalize_header(alias))
            if header:
                fields[field] = header
                evidence.append(f"{field} 命中表头 {header}")
                break
    if {"product_name", "reward_type", "content_id"}.issubset(fields):
        return ColumnMapping(fields=fields, mode="header_alias", confidence=0.96, evidence=evidence[:8])
    if not allow_inference:
        return ColumnMapping(fields=fields, mode="partial_header_alias", confidence=0.5, evidence=evidence[:8])

    inferred, inferred_evidence = _infer_mapping_from_values(rows, used=set(fields.values()))
    if infer_fields is not None:
        inferred = {field: header for field, header in inferred.items() if field in infer_fields}
        inferred_evidence = [item for item in inferred_evidence if item.split(" ", 1)[0] in infer_fields]
    for field, header in inferred.items():
        fields.setdefault(field, header)
    mode = "value_inference" if inferred else "partial_header_alias"
    confidence = 0.82 if {"product_name", "reward_type", "content_id"}.issubset(fields) else 0.55
    return ColumnMapping(fields=fields, mode=mode, confidence=confidence, evidence=[*evidence, *inferred_evidence][:10])


def _headers_from_rows(rows: list[dict[str, Any]]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for row in rows[:120]:
        for key in row:
            if key == "__row" or key in seen:
                continue
            seen.add(key)
            result.append(key)
    return result


def _infer_mapping_from_values(rows: list[dict[str, Any]], used: set[str]) -> tuple[dict[str, str], list[str]]:
    headers = [header for header in _headers_from_rows(rows) if header not in used]
    stats = {header: _column_stats(rows, header) for header in headers}
    evidence: list[str] = []
    fields: dict[str, str] = {}

    product_candidates = [
        (stat["product_score"], header)
        for header, stat in stats.items()
        if stat["text_count"] >= 3 and stat["distinct_text_count"] >= 3
    ]
    if product_candidates:
        _, header = max(product_candidates)
        fields["product_name"] = header
        evidence.append(f"product_name 根据文本列特征推断为 {header}")

    numeric_headers = [
        header
        for header, stat in stats.items()
        if header != fields.get("product_name") and stat["integer_count"] >= 3
    ]
    type_candidates = []
    for header in numeric_headers:
        stat = stats[header]
        if 1 <= stat["distinct_number_count"] <= 24 and stat["max_number"] <= 1000:
            type_candidates.append((stat["type_score"], header))
    if type_candidates:
        _, header = max(type_candidates)
        fields["reward_type"] = header
        evidence.append(f"reward_type 根据低基数数字列推断为 {header}")

    content_candidates = []
    for header in numeric_headers:
        if header == fields.get("reward_type"):
            continue
        stat = stats[header]
        if stat["distinct_number_count"] >= 3:
            content_candidates.append((stat["content_score"], header))
    if content_candidates:
        _, header = max(content_candidates)
        fields["content_id"] = header
        evidence.append(f"content_id 根据高基数数字列推断为 {header}")

    return fields, evidence


def _column_stats(rows: list[dict[str, Any]], header: str) -> dict[str, Any]:
    text_values: list[str] = []
    numeric_values: list[int] = []
    for row in rows[:5000]:
        value = _normalize_cell_value(row.get(header))
        if _is_blank(value):
            continue
        number = _integer_value(value)
        if number is not None:
            numeric_values.append(number)
            continue
        text = _text(value)
        if text and _looks_like_product_text(text):
            text_values.append(text)
    distinct_text = set(_lookup_key(value) for value in text_values)
    distinct_numbers = set(numeric_values)
    avg_text_len = sum(len(value) for value in text_values) / max(1, len(text_values))
    max_number = max(numeric_values or [0])
    return {
        "text_count": len(text_values),
        "distinct_text_count": len(distinct_text),
        "integer_count": len(numeric_values),
        "distinct_number_count": len(distinct_numbers),
        "max_number": max_number,
        "product_score": len(distinct_text) * 8 + len(text_values) * 0.5 - avg_text_len / 12,
        "type_score": len(numeric_values) * 2 - len(distinct_numbers) * 3 - max_number / 1000,
        "content_score": len(numeric_values) + len(distinct_numbers) * 3 + min(max_number, 1_000_000_000) / 1_000_000,
    }


def _normalize_cell_value(value: Any) -> Any:
    if isinstance(value, list):
        texts = [
            str(item.get("text", "")).strip()
            for item in value
            if isinstance(item, dict) and str(item.get("text", "")).strip()
        ]
        return " ".join(texts) if texts else value
    if isinstance(value, dict) and "text" in value:
        return value.get("text")
    return value


def _integer_value(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    return None


def _looks_like_product_text(value: str) -> bool:
    text = value.strip()
    if not text or len(text) > 80:
        return False
    lowered = text.lower()
    if lowered.startswith(("{", "[", "http", "=", "'")):
        return False
    if "cellposition" in lowered or "rangeid" in lowered or "sheetid" in lowered or "vlookup" in lowered or lowered.startswith("iferror"):
        return False
    return not _is_non_product_name(text)


def _similar_candidates(product_name: str, index: dict[str, dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    needle = _lookup_key(product_name)
    if not needle:
        return []
    scored: list[tuple[float, dict[str, Any]]] = []
    for key, entry in index.items():
        score = SequenceMatcher(None, needle, key).ratio()
        if needle in key or key in needle:
            score = max(score, 0.78)
        if score < 0.52:
            continue
        scored.append((score, entry))
    result = []
    for score, entry in sorted(scored, key=lambda item: item[0], reverse=True)[:limit]:
        result.append(
            {
                "product_name": entry["name"],
                "reward_type": entry["reward_type"],
                "content_id": entry["content_id"],
                "num": entry.get("num", 1),
                "confidence": round(min(score, 0.84), 2),
                "item_base_ref": entry["source_ref"],
                "evidence": "价值表商品名相似候选，需人工确认后使用。",
            }
        )
    return result


def _normalize_header(value: Any) -> str:
    return str(value or "").strip().replace(" ", "").replace("：", "").replace(":", "").lower()


def _lookup_key(value: Any) -> str:
    return str(value or "").strip().lower()


def _text(value: Any) -> str:
    return "" if _is_blank(value) else str(value).strip()


def _is_blank(value: Any) -> bool:
    return value is None or str(value).strip() == ""


def _is_non_product_name(name: str) -> bool:
    key = _lookup_key(name)
    if key in {
        "项目",
        "商品",
        "商品名",
        "商品名称",
        "合计",
        "总计",
        "小计",
        "策划备注",
        "特惠",
        "超值",
        "热卖",
        "server_activity_time",
        "take_effect_time",
        "cost_type",
        "cost_id",
        "time_type",
    }:
        return True
    if re.fullmatch(r"[a-z_][a-z0-9_]*", key):
        return True
    if re.search(r"20\d{2}-\d{1,2}-\d{1,2}", key):
        return True
    if key.isdigit():
        return True
    return False
