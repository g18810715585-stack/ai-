from __future__ import annotations

from typing import Any

from .models import Manifest, WorkbookIR


PLANNING_ROLES = {"planning", ""}
EXCHANGE_SHOP_HINTS = ("兑换店", "兑换商店", "active_shop", "reward.xlsx", "商品明细", "商店配置")


def build_structured_planning(manifest: Manifest, workbooks: list[WorkbookIR], item_resolution: dict[str, Any] | None = None) -> dict[str, Any]:
    """Extract high-value planning rows before the AI context is compressed.

    The raw planning sheet can contain hundreds of rows and many formula-only
    columns. This parser keeps only the rows that directly drive common shop
    configuration: activity settings, shop groups, item rows, and label rules.
    """
    role_by_source = {source.id: source.role for source in manifest.planning_sources}
    resolved_by_ref = _resolved_items_by_ref(item_resolution or {})
    sources: list[dict[str, Any]] = []
    for workbook in workbooks:
        if role_by_source.get(workbook.source_id, "planning") not in PLANNING_ROLES:
            continue
        for sheet in workbook.sheets:
            parsed = _parse_exchange_shop_sheet(workbook, sheet, resolved_by_ref)
            if parsed:
                sources.append(parsed)

    summary = {
        "source_count": len(sources),
        "activity_rows": sum(len(source.get("activity_rows") or []) for source in sources),
        "shop_groups": sum(len(source.get("shop_groups") or []) for source in sources),
        "shop_items": sum(len(source.get("shop_items") or []) for source in sources),
        "label_rules": sum(len(source.get("label_rules") or []) for source in sources),
    }
    return {
        "version": 1,
        "kind": "exchange_shop_structured_planning" if sources else "none",
        "summary": summary,
        "sources": sources,
    }


def compact_structured_planning_for_ai(structured: dict[str, Any], item_limit: int = 48) -> dict[str, Any]:
    if not structured or not structured.get("sources"):
        return {}
    sources = []
    for source in (structured.get("sources") or [])[:2]:
        sources.append(
            _drop_empty(
                {
                    "source_id": source.get("source_id"),
                    "sheet": source.get("sheet"),
                    "activity_type_hint": source.get("activity_type_hint"),
                    "activity_rows": [_compact_activity_row(row) for row in (source.get("activity_rows") or [])[:3]],
                    "shop_groups": [_compact_shop_group(row) for row in (source.get("shop_groups") or [])[:8]],
                    "shop_items": [_compact_shop_item(row) for row in (source.get("shop_items") or [])[:item_limit]],
                    "label_rules": (source.get("label_rules") or [])[:10],
                    "warnings": (source.get("warnings") or [])[:8],
                }
            )
        )
    return _drop_empty(
        {
            "version": structured.get("version"),
            "kind": structured.get("kind"),
            "summary": structured.get("summary") or {},
            "sources": sources,
        }
    )


def _parse_exchange_shop_sheet(workbook: WorkbookIR, sheet: Any, resolved_by_ref: dict[tuple[str, str, int], dict[str, Any]]) -> dict[str, Any] | None:
    rows = sorted((sheet.sample_rows or []), key=lambda item: int(item.get("__row") or 0))
    if not rows:
        return None
    if not _has_exchange_shop_hint(rows):
        return None

    activity_header = _find_header_row(rows, ("activity_id", "server_activity_time", "switch_name"))
    shop_header = _find_header_row(rows, ("cost_id", "cost_type", "排序起始"))
    item_header = _find_header_row(rows, ("商品名", "价格", "限购次数"))
    label_header = _find_header_row(rows, ("标签图集", "标签图标", "标签文本"))

    activity_rows = _activity_rows(rows, activity_header, shop_header, item_header)
    shop_groups = _shop_groups(rows, shop_header, item_header)
    label_rules = _label_rules(rows, label_header)
    shop_items = _shop_items(workbook, sheet.name, rows, item_header, label_rules, resolved_by_ref)

    warnings = []
    if item_header and not shop_items:
        warnings.append("检测到商品明细表头，但没有解析出商品行。")
    if shop_items and not shop_groups:
        warnings.append("检测到商品行，但没有解析出商店配置行。")
    if not activity_rows:
        warnings.append("没有解析出完整 activity 配置行，activity 字段需要 AI 或人工确认。")

    if not any([activity_rows, shop_groups, shop_items, label_rules]):
        return None
    return _drop_empty(
        {
            "source_id": workbook.source_id,
            "source_type": workbook.source_type.value if hasattr(workbook.source_type, "value") else str(workbook.source_type),
            "path": workbook.path,
            "url": workbook.url,
            "sheet": sheet.name,
            "activity_type_hint": "兑换店",
            "headers": {
                "activity_header_row": activity_header.get("__row") if activity_header else None,
                "shop_header_row": shop_header.get("__row") if shop_header else None,
                "item_header_row": item_header.get("__row") if item_header else None,
                "label_header_row": label_header.get("__row") if label_header else None,
            },
            "activity_rows": activity_rows,
            "shop_groups": shop_groups,
            "shop_items": shop_items,
            "label_rules": label_rules,
            "warnings": warnings,
        }
    )


def _has_exchange_shop_hint(rows: list[dict[str, Any]]) -> bool:
    text = "\n".join(str(value) for row in rows[:80] for value in row.values() if value not in (None, ""))
    return any(hint in text for hint in EXCHANGE_SHOP_HINTS)


def _find_header_row(rows: list[dict[str, Any]], required_values: tuple[str, ...]) -> dict[str, Any] | None:
    for row in rows:
        values = {_norm(value) for value in row.values() if value not in (None, "")}
        if all(any(required in value for value in values) for required in required_values):
            return row
    return None


def _activity_rows(
    rows: list[dict[str, Any]],
    header: dict[str, Any] | None,
    shop_header: dict[str, Any] | None,
    item_header: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not header:
        return []
    stop_rows = [int(row.get("__row") or 999999) for row in [shop_header, item_header] if row]
    stop_at = min(stop_rows) if stop_rows else 999999
    result = []
    for row in rows:
        row_number = int(row.get("__row") or 0)
        if row_number <= int(header.get("__row") or 0) or row_number >= stop_at:
            continue
        mapped = _map_with_header(row, header)
        if not _has_any(mapped, ("name", "备注", "server_activity_time", "type", "switch_name", "condition")):
            continue
        result.append(
            _drop_empty(
                {
                    "source_row": row_number,
                    "name": mapped.get("name") or mapped.get("备注"),
                    "server_activity_time": mapped.get("server_activity_time"),
                    "time_type": mapped.get("time_type"),
                    "take_effect_time": mapped.get("take_effect_time"),
                    "end_show_time": mapped.get("end_show_time"),
                    "faq": mapped.get("faq"),
                    "icon": mapped.get("icon"),
                    "describe": mapped.get("describe"),
                    "date_type": mapped.get("date_type"),
                    "date_show": mapped.get("date_show"),
                    "date_color": mapped.get("date_color"),
                    "date_dec": mapped.get("date_dec"),
                    "mail": mapped.get("mail"),
                    "weight": mapped.get("weight"),
                    "is_open": mapped.get("is_open"),
                    "planning_type": mapped.get("type"),
                    "MainUI_btn": mapped.get("MainUI_btn"),
                    "condition": mapped.get("condition"),
                    "server_open_day": mapped.get("server_open_day"),
                    "server_list": mapped.get("server_list"),
                    "season": mapped.get("season"),
                    "switch_name": mapped.get("switch_name"),
                    "show_type": mapped.get("show_type"),
                    "param": mapped.get("param"),
                    "param2": mapped.get("param2"),
                    "recycle": mapped.get("recycle"),
                    "pre_activity": mapped.get("pre_activity"),
                    "recycle_mail": mapped.get("recycle_mail"),
                    "raw": _non_empty_row(row, limit=36),
                }
            )
        )
    return result[:5]


def _shop_groups(rows: list[dict[str, Any]], header: dict[str, Any] | None, item_header: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not header:
        return []
    stop_at = int(item_header.get("__row") or 999999) if item_header else 999999
    result = []
    for row in rows:
        row_number = int(row.get("__row") or 0)
        if row_number <= int(header.get("__row") or 0) or row_number >= stop_at:
            continue
        mapped = _map_with_header(row, header)
        if not _has_any(mapped, ("商店组", "商店名称", "cost_id", "cost_type")):
            continue
        result.append(
            _drop_empty(
                {
                    "source_row": row_number,
                    "shop_group_label": mapped.get("商店组") or mapped.get("shop_group") or row.get("字段说明"),
                    "shop_name": mapped.get("商店名称") or mapped.get("name") or row.get("活动名"),
                    "cost_id": mapped.get("cost_id"),
                    "cost_type": mapped.get("cost_type"),
                    "sort_start": mapped.get("排序起始"),
                    "sort_step": mapped.get("排序步长"),
                    "activity_note": mapped.get("策划备注（活动") or mapped.get("策划备注（活动）") or row.get("结束后展示小时"),
                    "raw": _non_empty_row(row, limit=16),
                }
            )
        )
    return result[:12]


def _shop_items(
    workbook: WorkbookIR,
    sheet_name: str,
    rows: list[dict[str, Any]],
    header: dict[str, Any] | None,
    label_rules: list[dict[str, Any]],
    resolved_by_ref: dict[tuple[str, str, int], dict[str, Any]],
) -> list[dict[str, Any]]:
    if not header:
        return []
    labels_by_name = {str(rule.get("label") or ""): rule for rule in label_rules if rule.get("label")}
    result = []
    for row in rows:
        row_number = int(row.get("__row") or 0)
        if row_number <= int(header.get("__row") or 0):
            continue
        mapped = _map_with_header(row, header)
        product_name = _text(mapped.get("商品名") or mapped.get("product_name"))
        if not product_name or _is_non_product_name(product_name):
            continue
        label = _text(mapped.get("标签备注"))
        resolved = resolved_by_ref.get((workbook.source_id, sheet_name, row_number), {})
        result.append(
            _drop_empty(
                {
                    "source_row": row_number,
                    "shop_group_label": mapped.get("商店组"),
                    "order_index": mapped.get("序号"),
                    "label": label,
                    "label_rule": labels_by_name.get(label),
                    "product_name": product_name,
                    "planning_quantity": mapped.get("道具数量"),
                    "price": mapped.get("价格"),
                    "purchase_limit": mapped.get("限购次数"),
                    "item_value": mapped.get("道具价值"),
                    "currency_value": mapped.get("兑换币价值"),
                    "exchange_ratio": mapped.get("兑换反比"),
                    "total_cost": mapped.get("总消耗"),
                    "sort_order": mapped.get("排序"),
                    "show_group": mapped.get("道具显示分组"),
                    "group_title": mapped.get("分组标题"),
                    "server_list": mapped.get("服务器范围"),
                    "season": mapped.get("赛季字段"),
                    "condition": mapped.get("购买条件"),
                    "buy_time": mapped.get("可购买时间"),
                    "goto_value": mapped.get("跳转参数"),
                    "display_group_note": mapped.get("展示分组备注"),
                    "note": mapped.get("备注"),
                    "resolved_reward": _drop_empty(
                        {
                            "reward_type": resolved.get("reward_type"),
                            "content_id": resolved.get("content_id"),
                            "value_table_quantity": resolved.get("num"),
                            "confidence": resolved.get("confidence"),
                            "source": resolved.get("source"),
                        }
                    ),
                    "raw": _non_empty_row(row, limit=26),
                }
            )
        )
    return result[:120]


def _label_rules(rows: list[dict[str, Any]], header: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not header:
        return []
    result = []
    for row in rows:
        row_number = int(row.get("__row") or 0)
        if row_number <= int(header.get("__row") or 0):
            continue
        mapped = _map_with_header(row, header)
        label = mapped.get("策划备注") or row.get("活动开始|结束时间")
        if not label:
            continue
        result.append(
            _drop_empty(
                {
                    "source_row": row_number,
                    "label": label,
                    "title_artclass": mapped.get("标签图集") or row.get("字段说明"),
                    "title_icon": mapped.get("标签图标") or row.get("活动名"),
                    "title_text": mapped.get("标签文本") or row.get("策划备注"),
                }
            )
        )
    return result[:20]


def _map_with_header(row: dict[str, Any], header: dict[str, Any]) -> dict[str, Any]:
    mapped: dict[str, Any] = {}
    for source_field, canonical in header.items():
        if source_field == "__row" or canonical in (None, ""):
            continue
        value = row.get(source_field)
        if value in (None, ""):
            continue
        mapped[str(canonical).strip()] = value
    return mapped


def _resolved_items_by_ref(item_resolution: dict[str, Any]) -> dict[tuple[str, str, int], dict[str, Any]]:
    result: dict[tuple[str, str, int], dict[str, Any]] = {}
    for item in item_resolution.get("matches") or []:
        ref = item.get("planning_ref") or {}
        row = ref.get("row")
        if ref.get("workbook") and ref.get("sheet") and isinstance(row, int):
            result[(ref["workbook"], ref["sheet"], row)] = item
    return result


def _compact_activity_row(row: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "source_row",
        "name",
        "server_activity_time",
        "time_type",
        "take_effect_time",
        "end_show_time",
        "faq",
        "icon",
        "describe",
        "date_type",
        "date_show",
        "date_color",
        "date_dec",
        "mail",
        "weight",
        "is_open",
        "planning_type",
        "MainUI_btn",
        "condition",
        "server_open_day",
        "server_list",
        "season",
        "switch_name",
        "show_type",
        "param",
        "param2",
        "recycle",
        "pre_activity",
        "recycle_mail",
    ]
    return _drop_empty({key: row.get(key) for key in keys})


def _compact_shop_group(row: dict[str, Any]) -> dict[str, Any]:
    keys = ["source_row", "shop_group_label", "shop_name", "cost_id", "cost_type", "sort_start", "sort_step", "activity_note"]
    return _drop_empty({key: row.get(key) for key in keys})


def _compact_shop_item(row: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "source_row",
        "shop_group_label",
        "order_index",
        "label",
        "label_rule",
        "product_name",
        "planning_quantity",
        "price",
        "purchase_limit",
        "sort_order",
        "show_group",
        "group_title",
        "condition",
        "server_list",
        "season",
        "buy_time",
        "goto_value",
        "display_group_note",
        "note",
        "resolved_reward",
    ]
    return _drop_empty({key: row.get(key) for key in keys})


def _non_empty_row(row: dict[str, Any], limit: int) -> dict[str, Any]:
    result = {}
    for key, value in row.items():
        if key == "__row" or value in (None, ""):
            continue
        result[key] = value
        if len(result) >= limit:
            break
    return result


def _has_any(mapped: dict[str, Any], keys: tuple[str, ...]) -> bool:
    return any(mapped.get(key) not in (None, "") for key in keys)


def _text(value: Any) -> str:
    if value in (None, ""):
        return ""
    return str(value).strip()


def _norm(value: Any) -> str:
    return _text(value)


def _is_non_product_name(value: str) -> bool:
    text = value.strip()
    if not text:
        return True
    lowered = text.lower()
    blocked = {"商品名", "道具名", "name", "product", "item", "标签图标", "标签文本", "策划备注"}
    if text in blocked or lowered in blocked:
        return True
    if any(part in text for part in ("说明", "规范", "配置", "表头", "字段")):
        return True
    return False


def _drop_empty(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value not in (None, "", [], {})}
