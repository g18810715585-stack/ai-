from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import Manifest, Patch, SchemaBundle, WorkbookIR


KNOWLEDGE_FILES = {
    "experiences": "experiences.jsonl",
    "rules": "rules.jsonl",
    "activity_templates": "activity_templates.jsonl",
    "field_mappings": "field_mappings.jsonl",
    "field_dictionary": "field_dictionary.jsonl",
    "case_examples": "case_examples.jsonl",
    "structured_corrections": "structured_corrections.jsonl",
}

RECORD_ID_FIELDS = {
    "rules": "rule_id",
    "activity_templates": "template_id",
    "field_mappings": "mapping_id",
    "field_dictionary": "dictionary_id",
    "case_examples": "case_id",
    "structured_corrections": "correction_id",
}


DEFAULT_ACTIVITY_TEMPLATES: list[dict[str, Any]] = [
    {
        "template_id": "exchange_shop",
        "name": "兑换商店活动",
        "aliases": ["兑换", "商店", "兑换商店", "exchange", "商品兑换", "奖励兑换"],
        "target_tables": ["activity", "active_shop", "exchange", "reward", "goods", "key"],
        "relation_chain": ["activity", "active_shop", "exchange", "reward", "goods", "key"],
        "required_fields": {
            "activity": ["id", "活动标题", "活动时间类型", "活动生效时间", "活动形式模块"],
            "active_shop": ["商品组", "商品", "商品内容"],
            "exchange": ["唯一ID", "活动id", "商品内容", "支付价格"],
            "reward": ["id"],
            "goods": ["道具ID"],
            "key": ["UI_Title_001"],
        },
        "defaults": {"review_required": True},
        "confidence": 0.72,
        "evidence": ["builtin activity template"],
    },
    {
        "template_id": "point_mission",
        "name": "积分任务活动",
        "aliases": ["积分", "任务", "point", "mission", "任务目标", "活跃任务"],
        "target_tables": ["activity", "activity_point_mission", "activity_task_target", "reward", "key"],
        "relation_chain": ["activity", "activity_point_mission", "activity_task_target", "reward", "key"],
        "required_fields": {
            "activity": ["id", "活动标题", "活动形式模块"],
            "activity_point_mission": ["任务id", "组", "奖励"],
            "activity_task_target": ["id", "任务逻辑"],
            "reward": ["id"],
        },
        "defaults": {"review_required": True},
        "confidence": 0.68,
        "evidence": ["builtin activity template"],
    },
    {
        "template_id": "battle_pass",
        "name": "BP 通行证活动",
        "aliases": ["bp", "battlepass", "battle pass", "通行证", "战令", "赛季通行证"],
        "target_tables": ["activity", "activity_task_target", "activity_point_mission", "exchange", "reward", "goods", "key"],
        "relation_chain": ["activity", "activity_task_target", "activity_point_mission", "exchange", "reward", "goods", "key"],
        "required_fields": {
            "activity": ["id", "活动标题", "活动形式模块", "活动生效时间"],
            "activity_task_target": ["id", "任务逻辑", "目标值"],
            "activity_point_mission": ["任务id", "奖励", "积分"],
            "exchange": ["唯一ID", "商品内容", "支付价格"],
            "reward": ["id"],
            "goods": ["道具ID"],
        },
        "id_strategy": "活动主 ID 通常新建；奖励、商品、文案按规划和历史活动判断新建或复用。",
        "defaults": {"review_required": True},
        "confidence": 0.7,
        "evidence": ["builtin activity template"],
    },
    {
        "template_id": "pack",
        "name": "礼包活动",
        "aliases": ["礼包", "付费礼包", "pack", "充值", "购买"],
        "target_tables": ["activity", "exchange", "reward", "goods", "key"],
        "relation_chain": ["activity", "exchange", "reward", "goods", "key"],
        "required_fields": {
            "activity": ["id", "活动标题", "活动生效时间"],
            "exchange": ["唯一ID", "商品内容", "支付价格"],
            "reward": ["id"],
        },
        "defaults": {"review_required": True},
        "confidence": 0.66,
        "evidence": ["builtin activity template"],
    },
    {
        "template_id": "rank_reward",
        "name": "排行榜奖励活动",
        "aliases": ["排行", "排行榜", "排名", "rank", "榜单"],
        "target_tables": ["activity", "reward_rank", "reward", "mail", "key"],
        "relation_chain": ["activity", "reward_rank", "reward", "mail", "key"],
        "required_fields": {
            "activity": ["id", "活动标题"],
            "reward_rank": ["组"],
            "reward": ["id"],
            "mail": ["索引"],
        },
        "defaults": {"review_required": True},
        "confidence": 0.64,
        "evidence": ["builtin activity template"],
    },
    {
        "template_id": "drop_reward",
        "name": "掉落奖励活动",
        "aliases": ["掉落", "奖励", "drop", "收集", "产出"],
        "target_tables": ["activity", "activity_drop", "reward", "goods", "key"],
        "relation_chain": ["activity", "activity_drop", "reward", "goods", "key"],
        "required_fields": {
            "activity": ["id", "活动标题"],
            "activity_drop": ["组"],
            "reward": ["id"],
            "goods": ["道具ID"],
        },
        "defaults": {"review_required": True},
        "confidence": 0.62,
        "evidence": ["builtin activity template"],
    },
]


DEFAULT_FIELD_MAPPINGS: list[dict[str, Any]] = [
    {
        "mapping_id": "builtin_activity_id",
        "source_aliases": ["活动id", "活动ID", "活动编号", "活动"],
        "target_table": "activity",
        "target_field": "id",
        "confidence": 0.76,
        "evidence": ["builtin field mapping"],
    },
    {
        "mapping_id": "builtin_activity_title",
        "source_aliases": ["活动名", "活动名称", "活动标题", "标题", "名称"],
        "target_table": "activity",
        "target_field": "活动标题",
        "confidence": 0.72,
        "evidence": ["builtin field mapping"],
    },
    {
        "mapping_id": "builtin_goods_name",
        "source_aliases": ["商品名", "商品名称", "道具名", "道具名称", "奖励名称", "物品名"],
        "target_table": "goods",
        "target_field": "道具名",
        "confidence": 0.7,
        "evidence": ["builtin field mapping"],
    },
    {
        "mapping_id": "builtin_goods_id",
        "source_aliases": ["道具id", "道具ID", "商品id", "商品ID", "物品id", "item_id"],
        "target_table": "goods",
        "target_field": "道具ID",
        "confidence": 0.78,
        "evidence": ["builtin field mapping"],
    },
    {
        "mapping_id": "builtin_reward",
        "source_aliases": ["奖励", "奖励内容", "礼包内容", "掉落内容", "reward"],
        "target_table": "reward",
        "target_field": "id",
        "confidence": 0.68,
        "evidence": ["builtin field mapping"],
    },
    {
        "mapping_id": "builtin_price",
        "source_aliases": ["价格", "售价", "支付价格", "原价", "现价", "price"],
        "target_table": "exchange",
        "target_field": "支付价格",
        "confidence": 0.7,
        "evidence": ["builtin field mapping"],
    },
    {
        "mapping_id": "builtin_group",
        "source_aliases": ["组", "分组", "商品组", "奖励组", "group"],
        "target_table": "active_shop",
        "target_field": "商品组",
        "confidence": 0.68,
        "evidence": ["builtin field mapping"],
    },
    {
        "mapping_id": "builtin_key_text",
        "source_aliases": ["文案", "文本", "描述", "说明", "标题key", "key"],
        "target_table": "key",
        "target_field": "UI_Title_001",
        "confidence": 0.66,
        "evidence": ["builtin field mapping"],
    },
]


DEFAULT_FIELD_DICTIONARY: list[dict[str, Any]] = [
    {
        "dictionary_id": "builtin_activity_id",
        "target_table": "activity",
        "target_field": "id",
        "description": "活动唯一 ID，本次活动没有明确复用旧活动时通常新建。",
        "source_aliases": ["活动id", "活动ID", "活动编号", "活动"],
        "writable": True,
        "id_strategy": "new",
        "reference_table": "",
        "risk_note": "复用旧 ID 会影响旧活动，必须人工确认。",
        "confidence": 0.82,
        "enabled": True,
        "source": "builtin",
    },
    {
        "dictionary_id": "builtin_exchange_price",
        "target_table": "exchange",
        "target_field": "支付价格",
        "description": "兑换或购买的消耗价格，来源通常是规划里的价格、售价、消耗数量。",
        "source_aliases": ["价格", "售价", "支付价格", "消耗", "现价"],
        "writable": True,
        "id_strategy": "value",
        "reference_table": "",
        "risk_note": "货币类型和数量需要一起校验。",
        "confidence": 0.78,
        "enabled": True,
        "source": "builtin",
    },
    {
        "dictionary_id": "builtin_reward_id",
        "target_table": "reward",
        "target_field": "id",
        "description": "奖励组 ID，规划出现新的奖励组合时倾向新建，复用时必须确认奖励内容完全一致。",
        "source_aliases": ["奖励", "奖励内容", "奖励组", "礼包内容"],
        "writable": True,
        "id_strategy": "new_or_reuse",
        "reference_table": "goods",
        "risk_note": "奖励组复用错误会串到其他活动。",
        "confidence": 0.8,
        "enabled": True,
        "source": "builtin",
    },
    {
        "dictionary_id": "builtin_goods_id",
        "target_table": "goods",
        "target_field": "道具ID",
        "description": "道具或商品内容 ID，优先从价值表/商品表按名称匹配。",
        "source_aliases": ["道具id", "商品id", "物品id", "内容ID", "奖励ID"],
        "writable": False,
        "id_strategy": "lookup",
        "reference_table": "goods",
        "risk_note": "道具 ID 不应凭空编造，匹配不到时进入待确认。",
        "confidence": 0.82,
        "enabled": True,
        "source": "builtin",
    },
    {
        "dictionary_id": "builtin_key_text",
        "target_table": "key",
        "target_field": "UI_Title_001",
        "description": "标题或描述文案 key，规划里出现新文案时新建，旧文案复用必须确认适用范围。",
        "source_aliases": ["文案", "标题", "描述", "说明", "key"],
        "writable": True,
        "id_strategy": "new_or_reuse",
        "reference_table": "",
        "risk_note": "文案 key 复用会影响所有引用处。",
        "confidence": 0.74,
        "enabled": True,
        "source": "builtin",
    },
]


def knowledge_dir(base_dir: Path) -> Path:
    return base_dir / ".knowledge"


def ensure_knowledge_files(base_dir: Path) -> dict[str, str]:
    root = knowledge_dir(base_dir)
    root.mkdir(parents=True, exist_ok=True)
    paths = {name: str(root / filename) for name, filename in KNOWLEDGE_FILES.items()}
    for file_path in paths.values():
        Path(file_path).touch(exist_ok=True)
    return paths


def load_experience(base_dir: Path) -> dict[str, list[dict[str, Any]]]:
    root = knowledge_dir(base_dir)
    user_templates = _load_jsonl(root / KNOWLEDGE_FILES["activity_templates"])
    user_dictionary = _load_jsonl(root / KNOWLEDGE_FILES["field_dictionary"])
    return {
        "rules": _load_jsonl(root / KNOWLEDGE_FILES["rules"]),
        "activity_templates": _merge_records(DEFAULT_ACTIVITY_TEMPLATES, user_templates, "template_id"),
        "field_mappings": [*DEFAULT_FIELD_MAPPINGS, *_load_jsonl(root / KNOWLEDGE_FILES["field_mappings"])],
        "field_dictionary": _merge_records(DEFAULT_FIELD_DICTIONARY, user_dictionary, "dictionary_id"),
        "case_examples": _load_jsonl(root / KNOWLEDGE_FILES["case_examples"]),
        "structured_corrections": _load_jsonl(root / KNOWLEDGE_FILES["structured_corrections"]),
    }


def teach_experience(base_dir: Path, project: str, text: str, source: str = "manual") -> dict[str, Any]:
    ensure_knowledge_files(base_dir)
    root = knowledge_dir(base_dir)
    root.mkdir(parents=True, exist_ok=True)
    now = _now()
    text = text.strip()
    if not text:
        raise ValueError("经验内容不能为空")

    experience_id = _stable_id("experience", project, text, now)
    records = parse_experience_text(project, text, source=source, timestamp=now)
    _attach_experience_id(records, experience_id)
    for kind, items in records.items():
        path = root / KNOWLEDGE_FILES[kind]
        for item in items:
            _append_jsonl(path, item)
    entry = _experience_entry(experience_id, project, text, source, now, now, records)
    _append_jsonl(root / KNOWLEDGE_FILES["experiences"], entry)
    return {
        "experience_id": experience_id,
        "store": str(root),
        "created": {kind: len(items) for kind, items in records.items()},
        "entry": entry,
        "records": records,
    }


def list_saved_experiences(base_dir: Path, project: str | None = None) -> dict[str, Any]:
    root = knowledge_dir(base_dir)
    entries = _load_jsonl(root / KNOWLEDGE_FILES["experiences"])
    entry_ids = {item.get("experience_id") for item in entries}
    for rule in _load_jsonl(root / KNOWLEDGE_FILES["rules"]):
        if rule.get("experience_id") in entry_ids or rule.get("rule_id") in entry_ids:
            continue
        entries.append(
            {
                "experience_id": rule.get("experience_id") or rule.get("rule_id"),
                "project": rule.get("project", "default"),
                "title": rule.get("title") or str(rule.get("text", ""))[:40] or "历史经验",
                "text": rule.get("text", ""),
                "source": rule.get("source", "legacy"),
                "created_at": rule.get("created_at") or rule.get("last_used_at"),
                "updated_at": rule.get("last_used_at") or rule.get("created_at"),
                "record_counts": {"rules": 1, "activity_templates": 0, "field_mappings": 0, "case_examples": 0},
                "record_refs": {"rules": [rule.get("rule_id")], "activity_templates": [], "field_mappings": [], "case_examples": []},
                "legacy": True,
            }
        )
    if project:
        entries = [item for item in entries if item.get("project") == project]
    entries = [_normalize_experience_entry(item) for item in entries if item.get("experience_id")]
    entries.sort(key=lambda item: item.get("updated_at") or item.get("created_at") or "", reverse=True)
    return {"store": str(root), "count": len(entries), "experiences": entries}


def update_saved_experience(base_dir: Path, experience_id: str, text: str, project: str | None = None, source: str = "panel") -> dict[str, Any]:
    root = knowledge_dir(base_dir)
    root.mkdir(parents=True, exist_ok=True)
    text = text.strip()
    if not text:
        raise ValueError("经验内容不能为空")
    entries = _load_jsonl(root / KNOWLEDGE_FILES["experiences"])
    index = next((idx for idx, item in enumerate(entries) if item.get("experience_id") == experience_id), -1)
    now = _now()
    created_at = now
    record_refs: dict[str, list[str]] = {}
    if index >= 0:
        entry = entries[index]
        created_at = entry.get("created_at") or now
        project = project or entry.get("project") or "default"
        record_refs = entry.get("record_refs") or {}
    else:
        legacy = _find_legacy_rule(root, experience_id)
        if not legacy:
            raise ValueError(f"未找到经验：{experience_id}")
        created_at = legacy.get("created_at") or now
        project = project or legacy.get("project") or "default"
        record_refs = {"rules": [legacy.get("rule_id")], "activity_templates": [], "field_mappings": [], "case_examples": []}

    _remove_experience_records(root, experience_id, record_refs)
    records = parse_experience_text(project or "default", text, source=source, timestamp=now)
    _attach_experience_id(records, experience_id)
    for kind, items in records.items():
        for item in items:
            _append_jsonl(root / KNOWLEDGE_FILES[kind], item)
    updated = _experience_entry(experience_id, project or "default", text, source, created_at, now, records)
    if index >= 0:
        entries[index] = updated
    else:
        entries.append(updated)
    _write_jsonl(root / KNOWLEDGE_FILES["experiences"], entries)
    return {"store": str(root), "experience": updated, "updated": {kind: len(items) for kind, items in records.items()}}


def delete_saved_experience(base_dir: Path, experience_id: str) -> dict[str, Any]:
    root = knowledge_dir(base_dir)
    entries = _load_jsonl(root / KNOWLEDGE_FILES["experiences"])
    removed = [item for item in entries if item.get("experience_id") == experience_id]
    kept = [item for item in entries if item.get("experience_id") != experience_id]
    record_refs = removed[0].get("record_refs") if removed else {}
    if not removed:
        legacy = _find_legacy_rule(root, experience_id)
        if legacy:
            record_refs = {"rules": [legacy.get("rule_id")], "activity_templates": [], "field_mappings": [], "case_examples": []}
            removed = [{"experience_id": experience_id, "legacy": True}]
    if not removed:
        raise ValueError(f"未找到经验：{experience_id}")
    _remove_experience_records(root, experience_id, record_refs)
    _write_jsonl(root / KNOWLEDGE_FILES["experiences"], kept)
    return {"store": str(root), "deleted": experience_id, "remaining": len(kept)}


def list_activity_templates(base_dir: Path) -> dict[str, Any]:
    root = knowledge_dir(base_dir)
    user_records = _load_jsonl(root / KNOWLEDGE_FILES["activity_templates"])
    builtin_ids = {item["template_id"] for item in DEFAULT_ACTIVITY_TEMPLATES}
    templates = _merge_records(DEFAULT_ACTIVITY_TEMPLATES, user_records, "template_id")
    for item in templates:
        item["readonly"] = item.get("template_id") in builtin_ids and item.get("source", "builtin") == "builtin"
    templates.sort(key=lambda item: (not item.get("enabled", True), -float(item.get("confidence", 0)), item.get("name", "")))
    return {"store": str(root), "count": len(templates), "templates": templates}


def upsert_activity_template(base_dir: Path, template: dict[str, Any]) -> dict[str, Any]:
    root = knowledge_dir(base_dir)
    root.mkdir(parents=True, exist_ok=True)
    now = _now()
    normalized = _normalize_template_record(template, now)
    path = root / KNOWLEDGE_FILES["activity_templates"]
    records = _load_jsonl(path)
    index = next((idx for idx, item in enumerate(records) if item.get("template_id") == normalized["template_id"]), -1)
    if index >= 0:
        normalized["created_at"] = records[index].get("created_at") or now
        records[index] = normalized
    else:
        records.append(normalized)
    _write_jsonl(path, records)
    return {"store": str(root), "template": normalized}


def delete_activity_template(base_dir: Path, template_id: str) -> dict[str, Any]:
    root = knowledge_dir(base_dir)
    path = root / KNOWLEDGE_FILES["activity_templates"]
    records = _load_jsonl(path)
    builtin = next((item for item in DEFAULT_ACTIVITY_TEMPLATES if item.get("template_id") == template_id), None)
    kept = [item for item in records if item.get("template_id") != template_id]
    if builtin:
        disabled = dict(builtin)
        disabled.update({"enabled": False, "source": "panel_disabled", "updated_at": _now()})
        kept.append(disabled)
    elif len(kept) == len(records):
        raise ValueError(f"未找到活动模板：{template_id}")
    _write_jsonl(path, kept)
    return {"store": str(root), "deleted": template_id, "disabled_builtin": bool(builtin)}


def list_field_dictionary(base_dir: Path, table: str | None = None) -> dict[str, Any]:
    root = knowledge_dir(base_dir)
    user_records = _load_jsonl(root / KNOWLEDGE_FILES["field_dictionary"])
    builtin_ids = {item["dictionary_id"] for item in DEFAULT_FIELD_DICTIONARY}
    entries = _merge_records(DEFAULT_FIELD_DICTIONARY, user_records, "dictionary_id")
    if table:
        entries = [item for item in entries if item.get("target_table") == table]
    for item in entries:
        item["readonly"] = item.get("dictionary_id") in builtin_ids and item.get("source", "builtin") == "builtin"
    entries.sort(key=lambda item: (item.get("target_table", ""), item.get("target_field", "")))
    return {"store": str(root), "count": len(entries), "field_dictionary": entries}


def upsert_field_dictionary_entry(base_dir: Path, entry: dict[str, Any]) -> dict[str, Any]:
    root = knowledge_dir(base_dir)
    root.mkdir(parents=True, exist_ok=True)
    now = _now()
    normalized = _normalize_dictionary_record(entry, now)
    path = root / KNOWLEDGE_FILES["field_dictionary"]
    records = _load_jsonl(path)
    index = next((idx for idx, item in enumerate(records) if item.get("dictionary_id") == normalized["dictionary_id"]), -1)
    if index >= 0:
        normalized["created_at"] = records[index].get("created_at") or now
        records[index] = normalized
    else:
        records.append(normalized)
    _write_jsonl(path, records)
    return {"store": str(root), "entry": normalized}


def delete_field_dictionary_entry(base_dir: Path, dictionary_id: str) -> dict[str, Any]:
    root = knowledge_dir(base_dir)
    path = root / KNOWLEDGE_FILES["field_dictionary"]
    records = _load_jsonl(path)
    builtin = next((item for item in DEFAULT_FIELD_DICTIONARY if item.get("dictionary_id") == dictionary_id), None)
    kept = [item for item in records if item.get("dictionary_id") != dictionary_id]
    if builtin:
        disabled = dict(builtin)
        disabled.update({"enabled": False, "source": "panel_disabled", "updated_at": _now()})
        kept.append(disabled)
    elif len(kept) == len(records):
        raise ValueError(f"未找到字段字典：{dictionary_id}")
    _write_jsonl(path, kept)
    return {"store": str(root), "deleted": dictionary_id, "disabled_builtin": bool(builtin)}


def seed_field_dictionary_from_schema(base_dir: Path, schema: SchemaBundle) -> dict[str, Any]:
    root = knowledge_dir(base_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = root / KNOWLEDGE_FILES["field_dictionary"]
    records = _load_jsonl(path)
    existing = {item.get("dictionary_id") for item in [*DEFAULT_FIELD_DICTIONARY, *records]}
    now = _now()
    created = []
    for table_name, table in schema.tables.items():
        field_names = _ordered_unique([*table.primary_key, *table.fields.keys()])
        for field_name in field_names:
            dictionary_id = _stable_id("field-dict", table_name, field_name)
            if dictionary_id in existing:
                continue
            writable = (
                table.ai_write_permission != "readonly"
                and field_name not in table.block_update_fields
                and (not table.allow_update_fields or field_name in table.allow_update_fields or field_name in table.primary_key)
            )
            created.append(
                {
                    "dictionary_id": dictionary_id,
                    "target_table": table_name,
                    "target_field": field_name,
                    "description": "",
                    "source_aliases": [field_name],
                    "writable": writable,
                    "id_strategy": "unknown",
                    "reference_table": "",
                    "risk_note": "从配置表 schema 自动生成，建议人工补充字段含义和来源规划列名。",
                    "confidence": 0.55,
                    "enabled": True,
                    "source": "schema_scan",
                    "created_at": now,
                    "updated_at": now,
                }
            )
            existing.add(dictionary_id)
    if created:
        _write_jsonl(path, [*records, *created])
    return {"store": str(root), "created": len(created), "field_dictionary": created}


def parse_experience_text(project: str, text: str, source: str = "manual", timestamp: str | None = None) -> dict[str, list[dict[str, Any]]]:
    timestamp = timestamp or _now()
    normalized = _norm(text)
    rule_id = _stable_id("rule", project, text, timestamp)
    rule = {
        "rule_id": rule_id,
        "kind": "personal_rule",
        "project": project,
        "title": text[:40],
        "text": text,
        "scenario_tags": _scenario_tags(text),
        "applies_to_tables": _extract_table_names(text),
        "confidence": 0.72,
        "enabled": True,
        "source": source,
        "evidence": [f"{timestamp} {source}"],
        "created_at": timestamp,
        "last_used_at": timestamp,
    }

    mappings = []
    for mapping in DEFAULT_FIELD_MAPPINGS:
        if any(_norm(alias) in normalized for alias in mapping["source_aliases"]):
            item = dict(mapping)
            item["mapping_id"] = _stable_id("mapping", project, mapping["mapping_id"], text)
            item["project"] = project
            item["source"] = source
            item["confidence"] = min(0.95, float(item.get("confidence", 0.65)) + 0.08)
            item["evidence"] = [*item.get("evidence", []), text[:120]]
            item["created_at"] = timestamp
            mappings.append(item)

    mappings.extend(_parse_explicit_mappings(project, text, timestamp, source))
    return {
        "rules": [rule],
        "activity_templates": [],
        "field_mappings": _dedupe_records(mappings, "mapping_id"),
        "case_examples": [],
    }


def summarize_experience_locally(
    project: str,
    text: str,
    source: str = "summary_preview",
    existing_experiences: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    text = text.strip()
    if not text:
        raise ValueError("经验内容不能为空")
    records = parse_experience_text(project, text, source=source)
    table_names = _extract_table_names(text)
    scenario_tags = _scenario_tags(text)
    conflicts = detect_experience_conflicts(project, text, records, existing_experiences or [])
    review_text = _render_review_text(
        title=_summary_title(text, scenario_tags),
        raw_text=text,
        table_names=table_names,
        scenario_tags=scenario_tags,
        field_mappings=records["field_mappings"],
        questions=_local_questions(records, text),
    )
    return {
        "mode": "local",
        "summary_title": _summary_title(text, scenario_tags),
        "review_text": review_text,
        "activity_templates": records["activity_templates"],
        "field_mappings": records["field_mappings"],
        "personal_rules": records["rules"],
        "questions": _local_questions(records, text),
        "risk_notes": ["保存前请确认这些规则只影响待审核草案，不会直接写配置表。"],
        "conflicts": conflicts,
        "has_conflicts": bool(conflicts),
        "conflict_source": "local",
        "records_preview": records,
    }


def merge_experience_summary(project: str, raw_text: str, local_summary: dict[str, Any], ai_summary: dict[str, Any] | None = None, ai_error: str | None = None) -> dict[str, Any]:
    if not ai_summary:
        result = dict(local_summary)
        if ai_error:
            result["ai_error"] = ai_error
            result["risk_notes"] = [*result.get("risk_notes", []), "真实 AI 整理失败，当前展示的是本地规则整理结果。"]
        return result

    review_text = str(ai_summary.get("review_text") or "").strip()
    if not review_text:
        review_text = _render_ai_review_text(raw_text, ai_summary)
    records = parse_experience_text(project, review_text, source="ai_summary_preview")
    ai_conflicts = _normalize_conflicts(ai_summary.get("conflicts"))
    conflicts = ai_conflicts or local_summary.get("conflicts", [])
    return {
        "mode": "ai",
        "summary_title": str(ai_summary.get("summary_title") or local_summary.get("summary_title") or _summary_title(raw_text, [])),
        "review_text": review_text,
        "activity_templates": _list_of_dicts(ai_summary.get("activity_templates")),
        "field_mappings": _list_of_dicts(ai_summary.get("field_mappings")),
        "personal_rules": _list_of_dicts(ai_summary.get("personal_rules")),
        "questions": _string_list(ai_summary.get("questions")),
        "risk_notes": _string_list(ai_summary.get("risk_notes")) or local_summary.get("risk_notes", []),
        "conflicts": conflicts,
        "has_conflicts": bool(conflicts),
        "conflict_source": "ai" if ai_conflicts else local_summary.get("conflict_source", "local"),
        "records_preview": records,
        "local_preview": local_summary,
    }


def build_experience_context(
    base_dir: Path,
    manifest: Manifest,
    schema: SchemaBundle,
    workbooks: list[WorkbookIR],
    relationship_map: dict[str, Any],
) -> dict[str, Any]:
    store = load_experience(base_dir)
    signals = planning_signals(workbooks, manifest.run_instruction)
    target_tables = set(schema.tables.keys())
    templates = _match_templates(store["activity_templates"], signals, target_tables)
    field_mappings = _match_field_mappings(store["field_mappings"], signals, target_tables, schema)
    field_dictionary = _match_field_dictionary(store["field_dictionary"], signals, target_tables, schema)
    rules = _match_rules(store["rules"], manifest.project, signals, target_tables)
    cases = _match_cases(store["case_examples"], manifest.project, signals, target_tables)
    corrections = _match_structured_corrections(store["structured_corrections"], manifest.project, signals, target_tables)
    plan = build_config_plan(
        manifest,
        schema,
        relationship_map,
        templates,
        field_mappings,
        field_dictionary,
        rules,
        cases,
        corrections,
        signals,
    )
    return {
        "matched_activity_templates": templates[:5],
        "matched_field_mappings": field_mappings[:40],
        "field_dictionary_matches": field_dictionary[:60],
        "matched_rules": rules[:20],
        "similar_cases": cases[:8],
        "similar_case_summaries": _case_summaries(cases[:8]),
        "structured_corrections": corrections[:12],
        "config_plan": plan,
        "knowledge_counts": {key: len(value) for key, value in store.items()},
    }


def build_config_plan(
    manifest: Manifest,
    schema: SchemaBundle,
    relationship_map: dict[str, Any],
    templates: list[dict[str, Any]],
    field_mappings: list[dict[str, Any]],
    field_dictionary: list[dict[str, Any]],
    rules: list[dict[str, Any]],
    cases: list[dict[str, Any]],
    corrections: list[dict[str, Any]],
    signals: dict[str, Any],
) -> dict[str, Any]:
    top_template = templates[0] if templates else None
    current_targets = list(schema.tables.keys())
    template_tables = top_template.get("target_tables", []) if top_template else []
    recommended = _ordered_unique([
        *template_tables,
        *relationship_map.get("recommended_tables", []),
        *[table for mapping in field_mappings for table in [mapping.get("target_table")] if table],
        *[entry.get("target_table") for entry in field_dictionary if entry.get("target_table")],
    ])
    missing = []
    if not top_template:
        missing.append("未识别出明确活动模板，请补充活动类型或写入一条经验规则。")
    if not field_mappings and not field_dictionary:
        missing.append("规划表字段没有命中字段映射或字段字典，请说明规划列名对应哪些配置表字段。")
    if any(table not in current_targets for table in recommended[:12]):
        missing.append("部分推荐关联表尚未加入目标配置表。")
    if not signals.get("headers"):
        missing.append("规划表未识别出稳定表头。")

    pending = []
    for mapping in field_mappings:
        exists = _field_exists(schema, mapping.get("target_table"), mapping.get("target_field"))
        if mapping.get("confidence", 0) < 0.75 or not exists:
            pending.append(
                {
                    "type": "field_mapping",
                    "source_aliases": mapping.get("source_aliases", []),
                    "target_table": mapping.get("target_table"),
                    "target_field": mapping.get("target_field"),
                    "confidence": mapping.get("confidence", 0),
                    "reason": "低置信字段映射" if exists else "目标字段未在当前 schema 中确认",
                }
            )

    for entry in field_dictionary[:40]:
        if entry.get("writable") is False:
            pending.append(
                {
                    "type": "field_dictionary",
                    "source_aliases": entry.get("source_aliases", []),
                    "target_table": entry.get("target_table"),
                    "target_field": entry.get("target_field"),
                    "confidence": entry.get("confidence", 0),
                    "reason": "字段字典标记为不可直接写入，需要人工确认来源或引用。",
                }
            )
        elif entry.get("confidence", 0) < 0.72:
            pending.append(
                {
                    "type": "field_dictionary",
                    "source_aliases": entry.get("source_aliases", []),
                    "target_table": entry.get("target_table"),
                    "target_field": entry.get("target_field"),
                    "confidence": entry.get("confidence", 0),
                    "reason": "字段字典命中置信度偏低，需要确认规划列名和配置字段是否一致。",
                }
            )

    readiness = _plan_readiness(top_template, field_mappings, field_dictionary, cases, corrections, current_targets, recommended, missing)
    id_strategy = _id_strategy(top_template, field_dictionary, corrections)

    return {
        "activity_type": top_template.get("name") if top_template else "未识别",
        "activity_template_id": top_template.get("template_id") if top_template else None,
        "confidence": top_template.get("match_score", 0) if top_template else 0,
        "run_instruction": manifest.run_instruction,
        "current_target_tables": current_targets,
        "recommended_target_tables": [table for table in recommended if table not in current_targets],
        "all_recommended_tables": recommended,
        "relation_chain": top_template.get("relation_chain", []) if top_template else [],
        "required_fields": top_template.get("required_fields", {}) if top_template else {},
        "id_strategy": id_strategy,
        "matched_field_mappings": field_mappings[:40],
        "field_dictionary_matches": field_dictionary[:60],
        "matched_rules": rules[:20],
        "similar_cases": cases[:8],
        "similar_case_summaries": _case_summaries(cases[:8]),
        "structured_corrections": corrections[:12],
        "missing_information": missing,
        "pending_confirmations": pending[:40],
        "readiness": readiness,
        "planning_signals": {
            "sheet_names": signals.get("sheet_names", [])[:12],
            "headers": signals.get("headers", [])[:80],
        },
        "safety": "经验只影响待审核草案，不直接写表。",
    }


def append_case_from_patch(base_dir: Path, manifest: Manifest, patch: Patch, decision: str, note: str | None = None) -> dict[str, Any]:
    root = knowledge_dir(base_dir)
    root.mkdir(parents=True, exist_ok=True)
    tables = _ordered_unique([operation.target_table for operation in patch.operations])
    now = _now()
    case = {
        "case_id": _stable_id("case", manifest.project, patch.patch_id, decision, now),
        "project": manifest.project,
        "patch_id": patch.patch_id,
        "decision": decision,
        "target_tables": tables,
        "operation_count": len(patch.operations),
        "operation_types": sorted({operation.op for operation in patch.operations}),
        "note": note,
        "confidence": 0.78 if decision in {"accepted", "corrected"} else 0.45,
        "evidence": [f"{now} {decision}"],
        "created_at": now,
    }
    _append_jsonl(root / KNOWLEDGE_FILES["case_examples"], case)
    return case


def build_structured_correction(
    manifest: Manifest,
    patch: Patch,
    correction_text: str,
    review: dict[str, Any],
    record: dict[str, Any],
) -> dict[str, Any]:
    now = _now()
    notes = _split_correction_notes(correction_text)
    tables = _ordered_unique([*record.get("target_tables", []), *[operation.target_table for operation in patch.operations]])
    fields = _ordered_unique(
        [
            field
            for operation in patch.operations
            for field in [*operation.set.keys(), *[key for row in operation.rows for key in row.keys()]]
            if not str(field).startswith("__")
        ]
    )
    return {
        "correction_id": _stable_id("structured-correction", manifest.project, patch.patch_id, correction_text, now),
        "project": manifest.project,
        "patch_id": patch.patch_id,
        "activity_types": _scenario_tags(" ".join([manifest.run_instruction, correction_text, str(review.get("summary", ""))])),
        "target_tables": tables,
        "target_fields": fields[:80],
        "error_pattern": review.get("summary") or notes[0] if notes else correction_text[:160],
        "correct_practice": "；".join(notes[:6]) or correction_text[:240],
        "risk": "medium",
        "avoid_next_time": _string_list(review.get("avoid_next_time"))[:8] or notes[:8],
        "confidence": 0.76,
        "enabled": True,
        "source": "case_review",
        "evidence": [correction_text[:600]],
        "created_at": now,
        "updated_at": now,
    }


def save_structured_correction(base_dir: Path, correction: dict[str, Any]) -> dict[str, Any]:
    root = knowledge_dir(base_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = root / KNOWLEDGE_FILES["structured_corrections"]
    records = _load_jsonl(path)
    correction_id = correction.get("correction_id")
    if not correction_id:
        raise ValueError("结构化纠正规则缺少 correction_id")
    existing_index = next((idx for idx, item in enumerate(records) if item.get("correction_id") == correction_id), -1)
    if existing_index >= 0:
        records[existing_index] = {**records[existing_index], **correction, "updated_at": _now()}
    else:
        records.append(correction)
    _write_jsonl(path, records)
    return {"store": str(path), "correction": correction}


def planning_signals(workbooks: list[WorkbookIR], run_instruction: str = "") -> dict[str, Any]:
    sheet_names: list[str] = []
    headers: list[str] = []
    sample_values: list[str] = []
    for workbook in workbooks:
        for sheet in workbook.sheets:
            sheet_names.append(sheet.name)
            headers.extend(str(header) for header in sheet.headers if str(header).strip())
            for row in sheet.sample_rows[:8]:
                sample_values.extend(str(value) for value in row.values() if str(value).strip())
    text = "\n".join([run_instruction, *sheet_names, *headers, *sample_values])
    return {
        "sheet_names": _ordered_unique(sheet_names),
        "headers": _ordered_unique(headers),
        "run_instruction": run_instruction,
        "text": text,
        "normalized_text": _norm(text),
    }


def experience_context_payload(experience: dict[str, Any]) -> dict[str, Any]:
    return {
        "matched_activity_templates": experience.get("matched_activity_templates", []),
        "matched_field_mappings": experience.get("matched_field_mappings", []),
        "field_dictionary_matches": experience.get("field_dictionary_matches", []),
        "matched_rules": experience.get("matched_rules", []),
        "similar_cases": experience.get("similar_cases", []),
        "similar_case_summaries": experience.get("similar_case_summaries", []),
        "structured_corrections": experience.get("structured_corrections", []),
        "config_plan": experience.get("config_plan", {}),
    }


def _summary_title(text: str, scenario_tags: list[str]) -> str:
    if scenario_tags:
        return f"{scenario_tags[0]} 配表经验"
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), text.strip())
    return first_line[:32] or "配表经验"


def _render_review_text(
    title: str,
    raw_text: str,
    table_names: list[str],
    scenario_tags: list[str],
    field_mappings: list[dict[str, Any]],
    questions: list[str],
) -> str:
    lines = [
        f"经验标题：{title}",
        "",
        "适用场景：",
        *(f"- {tag}" for tag in scenario_tags[:8]),
    ]
    if not scenario_tags:
        lines.append("- 待确认活动类型")
    lines.extend(["", "相关配置表："])
    if table_names:
        lines.extend(f"- {name}" for name in table_names[:20])
    else:
        lines.append("- 待补充")
    lines.extend(["", "字段映射："])
    if field_mappings:
        for mapping in field_mappings[:20]:
            aliases = " / ".join(mapping.get("source_aliases", [])[:4]) or "规划字段"
            lines.append(f"- {aliases} -> {mapping.get('target_table')}.{mapping.get('target_field')}")
    else:
        lines.append("- 待补充，例如：规划里的商品名 -> goods.name")
    lines.extend(["", "个人规则：", f"- {raw_text.strip()}"])
    if questions:
        lines.extend(["", "保存前待确认：", *(f"- {item}" for item in questions)])
    return "\n".join(lines).strip()


def _render_ai_review_text(raw_text: str, ai_summary: dict[str, Any]) -> str:
    title = str(ai_summary.get("summary_title") or "配表经验").strip()
    lines = [f"经验标题：{title}", "", "个人规则：", f"- {raw_text.strip()}"]
    templates = _list_of_dicts(ai_summary.get("activity_templates"))
    if templates:
        lines.extend(["", "活动模板："])
        for template in templates[:8]:
            name = template.get("name") or template.get("template_id") or "未命名模板"
            tables = ", ".join(_string_list(template.get("target_tables")))
            lines.append(f"- {name}：{tables}")
    mappings = _list_of_dicts(ai_summary.get("field_mappings"))
    if mappings:
        lines.extend(["", "字段映射："])
        for mapping in mappings[:20]:
            aliases = " / ".join(_string_list(mapping.get("source_aliases"))[:4]) or "规划字段"
            lines.append(f"- {aliases} -> {mapping.get('target_table')}.{mapping.get('target_field')}")
    questions = _string_list(ai_summary.get("questions"))
    if questions:
        lines.extend(["", "保存前待确认：", *(f"- {item}" for item in questions)])
    return "\n".join(lines).strip()


def _local_questions(records: dict[str, list[dict[str, Any]]], text: str) -> list[str]:
    questions = []
    if not _scenario_tags(text):
        questions.append("如果这是新的活动类型，请到“活动模板”页签新建模板；历史经验不会自动创建模板。")
    if not records.get("field_mappings") and "->" not in text:
        questions.append("是否有规划列名到配置字段的映射？建议写成：规划列名 -> table.field。")
    if not _extract_table_names(text):
        questions.append("这条经验适用于哪些配置表？")
    return questions


def detect_experience_conflicts(
    project: str,
    text: str,
    records: dict[str, list[dict[str, Any]]],
    existing_experiences: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    new_tables = set(_extract_table_names(text))
    new_scenarios = set(_scenario_tags(text))
    new_mappings = _mapping_targets(records.get("field_mappings", []))
    new_policy = _policy_flags(text)

    for existing in existing_experiences:
        existing_text = str(existing.get("text") or existing.get("review_text") or "")
        if not existing_text.strip():
            continue
        existing_records = parse_experience_text(str(existing.get("project") or project), existing_text, source="conflict_scan")
        existing_tables = set(_extract_table_names(existing_text))
        existing_scenarios = set(_scenario_tags(existing_text))
        related = bool((new_tables & existing_tables) or (new_scenarios & existing_scenarios) or not (new_tables or existing_tables))

        for alias, target in new_mappings.items():
            old_target = _mapping_targets(existing_records.get("field_mappings", [])).get(alias)
            if old_target and old_target != target:
                conflicts.append(
                    _conflict_item(
                        "field_mapping",
                        existing,
                        f"字段映射冲突：{alias} 在新经验中指向 {target}，旧经验中指向 {old_target}",
                        new_value=f"{alias} -> {target}",
                        existing_value=f"{alias} -> {old_target}",
                        severity="high",
                    )
                )

        if related:
            old_policy = _policy_flags(existing_text)
            for left, right, reason in [
                ("preserve", "overwrite", "一个经验要求保留旧值，另一个经验倾向覆盖/改写。"),
                ("manual_confirm", "auto_write", "一个经验要求人工确认，另一个经验倾向自动写入。"),
                ("reuse_id", "new_id", "一个经验要求复用旧 ID，另一个经验倾向每次新建 ID。"),
            ]:
                if new_policy[left] and old_policy[right]:
                    conflicts.append(
                        _conflict_item("rule_policy", existing, reason, new_value=left, existing_value=right, severity="medium")
                    )
                if new_policy[right] and old_policy[left]:
                    conflicts.append(
                        _conflict_item("rule_policy", existing, reason, new_value=right, existing_value=left, severity="medium")
                    )

        if len(conflicts) >= 10:
            break
    return _dedupe_conflicts(conflicts)


def _mapping_targets(mappings: list[dict[str, Any]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for mapping in mappings:
        target = f"{mapping.get('target_table')}.{mapping.get('target_field')}"
        if "." not in target or target.startswith("None.") or target.endswith(".None"):
            continue
        for alias in mapping.get("source_aliases", []):
            key = _norm(str(alias))
            if key:
                result[key] = target
    return result


def _policy_flags(text: str) -> dict[str, bool]:
    normalized = _norm(text)
    preserve = any(word in normalized for word in ["保留", "不覆盖", "不要覆盖", "沿用", "保留旧值"])
    overwrite = any(word in normalized for word in ["覆盖", "改写", "替换", "重填", "直接写"])
    if preserve and any(word in normalized for word in ["不覆盖", "不要覆盖"]):
        overwrite = False
    manual_confirm = any(word in normalized for word in ["人工确认", "手动确认", "待确认", "不要自动", "必须确认"])
    auto_write = any(word in normalized for word in ["自动写", "自动补齐", "直接生成", "无需确认"])
    if manual_confirm and "不要自动" in normalized:
        auto_write = False
    reuse_id = any(word in normalized for word in ["复用id", "沿用id", "保留id", "不要新建id"])
    new_id = any(word in normalized for word in ["新建id", "每次新建", "重新生成id", "新开id"])
    if reuse_id and "不要新建id" in normalized:
        new_id = False
    return {
        "preserve": preserve,
        "overwrite": overwrite,
        "manual_confirm": manual_confirm,
        "auto_write": auto_write,
        "reuse_id": reuse_id,
        "new_id": new_id,
    }


def _conflict_item(
    conflict_type: str,
    existing: dict[str, Any],
    reason: str,
    new_value: str,
    existing_value: str,
    severity: str,
) -> dict[str, Any]:
    return {
        "conflict_id": _stable_id("experience-conflict", conflict_type, existing.get("experience_id"), reason, new_value, existing_value),
        "conflict_type": conflict_type,
        "severity": severity,
        "existing_experience_id": existing.get("experience_id"),
        "existing_title": existing.get("title") or "历史经验",
        "existing_created_at": existing.get("created_at"),
        "reason": reason,
        "new_value": new_value,
        "existing_value": existing_value,
        "recommendation": "保存前请确认这条新经验是否要覆盖你的旧习惯，或改写为更明确的适用场景。",
    }


def _normalize_conflicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    conflicts = []
    for item in value:
        if isinstance(item, dict):
            reason = str(item.get("reason") or item.get("summary") or "").strip()
            if reason:
                conflicts.append(
                    {
                        "conflict_id": str(item.get("conflict_id") or _stable_id("experience-conflict-ai", reason))[:32],
                        "conflict_type": str(item.get("conflict_type") or item.get("type") or "ai_review"),
                        "severity": str(item.get("severity") or "medium"),
                        "existing_experience_id": item.get("existing_experience_id"),
                        "existing_title": item.get("existing_title") or item.get("title"),
                        "existing_created_at": item.get("existing_created_at"),
                        "reason": reason,
                        "new_value": str(item.get("new_value") or ""),
                        "existing_value": str(item.get("existing_value") or ""),
                        "recommendation": str(item.get("recommendation") or "保存前请确认是否继续录入。"),
                    }
                )
    return _dedupe_conflicts(conflicts)


def _dedupe_conflicts(conflicts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    result = []
    for conflict in conflicts:
        key = (
            conflict.get("conflict_type"),
            conflict.get("existing_experience_id"),
            conflict.get("reason"),
            conflict.get("new_value"),
            conflict.get("existing_value"),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(conflict)
    return result[:10]


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _normalize_template_record(template: dict[str, Any], timestamp: str) -> dict[str, Any]:
    name = str(template.get("name") or template.get("activity_type") or "未命名活动模板").strip()
    template_id = str(template.get("template_id") or _stable_id("template", name, timestamp)).strip()
    return {
        "template_id": template_id,
        "name": name,
        "aliases": _string_list(template.get("aliases")) or [name],
        "target_tables": _string_list(template.get("target_tables")),
        "relation_chain": _string_list(template.get("relation_chain")),
        "required_fields": template.get("required_fields") if isinstance(template.get("required_fields"), dict) else {},
        "id_strategy": str(template.get("id_strategy") or "").strip(),
        "risk_notes": _string_list(template.get("risk_notes")),
        "defaults": template.get("defaults") if isinstance(template.get("defaults"), dict) else {"review_required": True},
        "confidence": _clamp_confidence(template.get("confidence"), 0.72),
        "enabled": bool(template.get("enabled", True)),
        "source": str(template.get("source") or "activity_template_panel"),
        "evidence": _string_list(template.get("evidence"))[:8],
        "created_at": str(template.get("created_at") or timestamp),
        "updated_at": timestamp,
    }


def _normalize_dictionary_record(entry: dict[str, Any], timestamp: str) -> dict[str, Any]:
    table = str(entry.get("target_table") or entry.get("table") or "").strip()
    field = str(entry.get("target_field") or entry.get("field") or "").strip()
    if not table or not field:
        raise ValueError("字段字典必须包含 target_table 和 target_field")
    dictionary_id = str(entry.get("dictionary_id") or _stable_id("field-dict", table, field)).strip()
    return {
        "dictionary_id": dictionary_id,
        "target_table": table,
        "target_field": field,
        "description": str(entry.get("description") or "").strip(),
        "source_aliases": _string_list(entry.get("source_aliases")) or [field],
        "writable": bool(entry.get("writable", True)),
        "id_strategy": str(entry.get("id_strategy") or "unknown").strip(),
        "reference_table": str(entry.get("reference_table") or "").strip(),
        "risk_note": str(entry.get("risk_note") or "").strip(),
        "confidence": _clamp_confidence(entry.get("confidence"), 0.72),
        "enabled": bool(entry.get("enabled", True)),
        "source": str(entry.get("source") or "panel"),
        "evidence": _string_list(entry.get("evidence"))[:8],
        "created_at": str(entry.get("created_at") or timestamp),
        "updated_at": timestamp,
    }


def _clamp_confidence(value: Any, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = fallback
    return round(max(0.0, min(0.99, number)), 3)


def _match_templates(templates: list[dict[str, Any]], signals: dict[str, Any], target_tables: set[str]) -> list[dict[str, Any]]:
    text = signals.get("normalized_text", "")
    scored = []
    for template in templates:
        if not template.get("enabled", True):
            continue
        score = float(template.get("confidence", 0.5))
        hits = [alias for alias in template.get("aliases", []) if _norm(alias) in text]
        if hits:
            score += min(0.22, 0.08 * len(hits))
        table_overlap = len(set(template.get("target_tables", [])) & target_tables)
        if table_overlap:
            score += min(0.12, table_overlap * 0.02)
        if score >= 0.58 and (hits or table_overlap >= 2):
            item = dict(template)
            item["match_score"] = round(min(score, 0.98), 3)
            item["matched_aliases"] = hits[:8]
            scored.append(item)
    return sorted(scored, key=lambda item: (-item["match_score"], item.get("name", "")))


def _match_field_dictionary(
    entries: list[dict[str, Any]],
    signals: dict[str, Any],
    target_tables: set[str],
    schema: SchemaBundle,
) -> list[dict[str, Any]]:
    text = signals.get("normalized_text", "")
    headers = {_norm(header) for header in signals.get("headers", [])}
    scored = []
    for entry in entries:
        if not entry.get("enabled", True):
            continue
        table = entry.get("target_table")
        field = entry.get("target_field")
        if table not in target_tables or not _field_exists(schema, table, field):
            continue
        aliases = _ordered_unique([str(field), *entry.get("source_aliases", [])])
        hits = [alias for alias in aliases if _norm(alias) and (_norm(alias) in text or _norm(alias) in headers)]
        if not hits and entry.get("source") != "builtin":
            continue
        score = float(entry.get("confidence", 0.55))
        if hits:
            score += min(0.2, len(hits) * 0.05)
        if table in target_tables:
            score += 0.04
        if entry.get("writable") is False:
            score -= 0.04
        if score < 0.5:
            continue
        item = dict(entry)
        item["confidence"] = round(max(0.0, min(score, 0.98)), 3)
        item["matched_aliases"] = hits[:8]
        scored.append(item)
    return sorted(scored, key=lambda item: (-item["confidence"], item.get("target_table", ""), item.get("target_field", "")))


def _match_field_mappings(
    mappings: list[dict[str, Any]],
    signals: dict[str, Any],
    target_tables: set[str],
    schema: SchemaBundle,
) -> list[dict[str, Any]]:
    text = signals.get("normalized_text", "")
    scored = []
    for mapping in mappings:
        aliases = mapping.get("source_aliases", [])
        hits = [alias for alias in aliases if _norm(alias) in text]
        if not hits:
            continue
        table = mapping.get("target_table")
        score = float(mapping.get("confidence", 0.55)) + min(0.15, len(hits) * 0.04)
        if table in target_tables:
            score += 0.08
        exists = _field_exists(schema, table, mapping.get("target_field"))
        item = dict(mapping)
        item["confidence"] = round(min(score, 0.98), 3)
        item["matched_aliases"] = hits[:8]
        item["target_field_exists"] = exists
        scored.append(item)
    return sorted(scored, key=lambda item: (-item["confidence"], item.get("target_table", ""), item.get("target_field", "")))


def _match_rules(rules: list[dict[str, Any]], project: str, signals: dict[str, Any], target_tables: set[str]) -> list[dict[str, Any]]:
    text = signals.get("normalized_text", "")
    scored = []
    for rule in rules:
        if not rule.get("enabled", True):
            continue
        score = float(rule.get("confidence", 0.5))
        if rule.get("project") == project:
            score += 0.08
        overlap = len(set(rule.get("applies_to_tables", [])) & target_tables)
        if overlap:
            score += min(0.12, overlap * 0.04)
        tag_hits = [tag for tag in rule.get("scenario_tags", []) if _norm(tag) in text]
        if tag_hits:
            score += min(0.18, len(tag_hits) * 0.06)
        if score >= 0.55 and (overlap or tag_hits or rule.get("project") == project):
            item = dict(rule)
            item["match_score"] = round(min(score, 0.98), 3)
            item["matched_tags"] = tag_hits
            scored.append(item)
    return sorted(scored, key=lambda item: (-item["match_score"], item.get("title", "")))


def _match_cases(cases: list[dict[str, Any]], project: str, signals: dict[str, Any], target_tables: set[str]) -> list[dict[str, Any]]:
    scored = []
    text = signals.get("normalized_text", "")
    for case in cases:
        score = float(case.get("confidence", 0.5))
        if case.get("project") == project:
            score += 0.08
        overlap = len(set(case.get("target_tables", [])) & target_tables)
        if overlap:
            score += min(0.18, overlap * 0.05)
        review = case.get("case_review") or {}
        review_bits = []
        for key in ("summary", "mistakes", "lessons", "avoid_next_time"):
            value = review.get(key)
            if isinstance(value, list):
                review_bits.extend(str(item) for item in value)
            elif value:
                review_bits.append(str(value))
        note = _norm(" ".join([str(case.get("note", "")), str(case.get("correction", "")), *review_bits]))
        if note and note in text:
            score += 0.1
        elif note:
            text_hits = sum(1 for chunk in review_bits if _norm(chunk) and _norm(chunk) in text)
            if text_hits:
                score += min(0.18, text_hits * 0.06)
        if case.get("decision") == "corrected":
            score += 0.08
        if score >= 0.55 and (overlap or case.get("project") == project):
            item = dict(case)
            item["match_score"] = round(min(score, 0.98), 3)
            scored.append(item)
    return sorted(scored, key=lambda item: (-item["match_score"], item.get("created_at", "")))


def _match_structured_corrections(
    corrections: list[dict[str, Any]],
    project: str,
    signals: dict[str, Any],
    target_tables: set[str],
) -> list[dict[str, Any]]:
    text = signals.get("normalized_text", "")
    scored = []
    for correction in corrections:
        if not correction.get("enabled", True):
            continue
        score = float(correction.get("confidence", 0.55))
        if correction.get("project") == project:
            score += 0.08
        overlap = len(set(correction.get("target_tables", [])) & target_tables)
        if overlap:
            score += min(0.18, overlap * 0.06)
        corpus = _norm(" ".join(_string_list(correction.get("activity_types")) + _string_list(correction.get("target_fields"))))
        if corpus and corpus in text:
            score += 0.12
        if score >= 0.55 and (overlap or correction.get("project") == project):
            item = dict(correction)
            item["match_score"] = round(min(score, 0.98), 3)
            scored.append(item)
    return sorted(scored, key=lambda item: (-item["match_score"], item.get("updated_at", item.get("created_at", ""))))


def _case_summaries(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries = []
    for case in cases:
        review = case.get("case_review") or {}
        summaries.append(
            {
                "case_id": case.get("case_id"),
                "patch_id": case.get("patch_id"),
                "decision": case.get("decision"),
                "target_tables": (case.get("target_tables") or [])[:12],
                "operation_count": case.get("operation_count"),
                "summary": review.get("summary") or case.get("note"),
                "lessons": _string_list(review.get("lessons"))[:5],
                "avoid_next_time": _string_list(review.get("avoid_next_time"))[:5],
                "match_score": case.get("match_score"),
            }
        )
    return summaries


def _plan_readiness(
    template: dict[str, Any] | None,
    mappings: list[dict[str, Any]],
    dictionary: list[dict[str, Any]],
    cases: list[dict[str, Any]],
    corrections: list[dict[str, Any]],
    current_targets: list[str],
    recommended: list[str],
    missing: list[str],
) -> dict[str, Any]:
    score = 0
    if template:
        score += 30
    if mappings:
        score += min(25, len(mappings) * 4)
    if dictionary:
        score += min(20, len(dictionary) * 2)
    if current_targets:
        score += 10
    if cases or corrections:
        score += 10
    if recommended and not any(table not in current_targets for table in recommended[:8]):
        score += 5
    blockers = [item for item in missing if "未识别" in item or "字段映射" in item]
    if blockers:
        score = min(score, 65)
    status = "ready" if score >= 75 and not blockers else "needs_review" if score >= 55 else "needs_info"
    return {"score": score, "status": status, "blockers": blockers[:6]}


def _id_strategy(
    template: dict[str, Any] | None,
    dictionary: list[dict[str, Any]],
    corrections: list[dict[str, Any]],
) -> dict[str, Any]:
    by_table: dict[str, list[dict[str, Any]]] = {}
    for entry in dictionary:
        strategy = entry.get("id_strategy")
        if not strategy or strategy == "unknown":
            continue
        by_table.setdefault(entry.get("target_table"), []).append(
            {
                "field": entry.get("target_field"),
                "strategy": strategy,
                "risk_note": entry.get("risk_note"),
                "confidence": entry.get("confidence"),
            }
        )
    return {
        "template_rule": template.get("id_strategy") if template else "",
        "field_rules": by_table,
        "correction_rules": [
            {
                "correction_id": item.get("correction_id"),
                "correct_practice": item.get("correct_practice"),
                "avoid_next_time": item.get("avoid_next_time"),
                "match_score": item.get("match_score"),
            }
            for item in corrections[:6]
        ],
    }


def _parse_explicit_mappings(project: str, text: str, timestamp: str, source: str) -> list[dict[str, Any]]:
    mappings = []
    arrow_pattern = re.compile(r"([\u4e00-\u9fffA-Za-z0-9_/\- ]{1,32})\s*(?:->|=>|映射到|对应到|maps?\s+to)\s*([A-Za-z][A-Za-z0-9_]*)[.\s。．]+([\u4e00-\u9fffA-Za-z0-9_]{1,48})", re.IGNORECASE)
    for match in arrow_pattern.finditer(text):
        alias = match.group(1).strip(" ：:，,。.")
        table = match.group(2).strip()
        field = match.group(3).strip(" ：:，,。.")
        if not alias or not table or not field:
            continue
        mappings.append(
            {
                "mapping_id": _stable_id("mapping", project, alias, table, field, timestamp),
                "project": project,
                "source_aliases": [alias],
                "target_table": table,
                "target_field": field,
                "confidence": 0.84,
                "source": source,
                "evidence": [text[:160]],
                "created_at": timestamp,
            }
        )
    pattern = re.compile(r"([\u4e00-\u9fa5A-Za-z0-9_/\- ]{1,24})\s*(?:通常|一般|可以|要)?\s*对应\s*([A-Za-z][A-Za-z0-9_]*)[.。\s]+([\u4e00-\u9fa5A-Za-z0-9_]{1,32})")
    for match in pattern.finditer(text):
        alias = match.group(1).strip(" ，,。")
        table = match.group(2).strip()
        field = match.group(3).strip(" ，,。")
        if not alias or not table or not field:
            continue
        mappings.append(
            {
                "mapping_id": _stable_id("mapping", project, alias, table, field, timestamp),
                "project": project,
                "source_aliases": [alias],
                "target_table": table,
                "target_field": field,
                "confidence": 0.82,
                "source": source,
                "evidence": [text[:160]],
                "created_at": timestamp,
            }
        )
    return mappings


def _extract_table_names(text: str) -> list[str]:
    names = re.findall(r"\b[A-Za-z][A-Za-z0-9_]{2,}\b", text)
    ignored = {"AI", "JSON", "Patch", "Excel", "ID"}
    return _ordered_unique([name for name in names if name not in ignored and "_" in name])


def _scenario_tags(text: str) -> list[str]:
    tags = []
    for template in DEFAULT_ACTIVITY_TEMPLATES:
        if any(alias in text for alias in template["aliases"]):
            tags.append(template["template_id"])
            tags.append(template["name"])
    return _ordered_unique(tags)


def _field_exists(schema: SchemaBundle, table_name: str | None, field_name: str | None) -> bool:
    if not table_name or not field_name or table_name not in schema.tables:
        return False
    table = schema.tables[table_name]
    return field_name in table.fields or field_name in table.primary_key


def _attach_experience_id(records: dict[str, list[dict[str, Any]]], experience_id: str) -> None:
    for items in records.values():
        for item in items:
            item["experience_id"] = experience_id


def _experience_entry(
    experience_id: str,
    project: str,
    text: str,
    source: str,
    created_at: str,
    updated_at: str,
    records: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    return {
        "experience_id": experience_id,
        "project": project,
        "title": _entry_title(text),
        "text": text,
        "source": source,
        "created_at": created_at,
        "updated_at": updated_at,
        "record_counts": {kind: len(items) for kind, items in records.items()},
        "record_refs": _record_refs(records),
    }


def _entry_title(text: str) -> str:
    for line in text.splitlines():
        line = line.strip().lstrip("-# ")
        if not line:
            continue
        if line.startswith("经验标题"):
            _, _, value = line.partition("：")
            line = value.strip() or line
        return line[:48]
    return "配表经验"


def _record_refs(records: dict[str, list[dict[str, Any]]]) -> dict[str, list[str]]:
    refs: dict[str, list[str]] = {}
    for kind, items in records.items():
        id_field = RECORD_ID_FIELDS.get(kind)
        refs[kind] = [str(item.get(id_field)) for item in items if id_field and item.get(id_field)]
    return refs


def _normalize_experience_entry(item: dict[str, Any]) -> dict[str, Any]:
    text = str(item.get("text") or "")
    return {
        "experience_id": item.get("experience_id"),
        "project": item.get("project", "default"),
        "title": item.get("title") or _entry_title(text),
        "text": text,
        "source": item.get("source", ""),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at") or item.get("created_at"),
        "record_counts": item.get("record_counts") or {},
        "record_refs": item.get("record_refs") or {},
        "legacy": bool(item.get("legacy")),
    }


def _find_legacy_rule(root: Path, experience_id: str) -> dict[str, Any] | None:
    for rule in _load_jsonl(root / KNOWLEDGE_FILES["rules"]):
        if rule.get("rule_id") == experience_id or rule.get("experience_id") == experience_id:
            return rule
    return None


def _remove_experience_records(root: Path, experience_id: str, record_refs: dict[str, list[str]] | None) -> None:
    record_refs = record_refs or {}
    for kind, id_field in RECORD_ID_FIELDS.items():
        path = root / KNOWLEDGE_FILES[kind]
        ids = {item for item in record_refs.get(kind, []) if item}
        kept = []
        for item in _load_jsonl(path):
            item_id = item.get(id_field)
            if item.get("experience_id") == experience_id or item_id in ids:
                continue
            kept.append(item)
        _write_jsonl(path, kept)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return items


def _append_jsonl(path: Path, item: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")))
        handle.write("\n")


def _write_jsonl(path: Path, items: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")


def _merge_records(defaults: list[dict[str, Any]], records: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in defaults:
        item_key = item.get(key)
        if item_key:
            merged[str(item_key)] = dict(item)
    for item in records:
        item_key = item.get(key)
        if not item_key:
            continue
        previous = merged.get(str(item_key), {})
        merged[str(item_key)] = {**previous, **item}
    return list(merged.values())


def _dedupe_records(items: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    result = {}
    for item in items:
        result[item[key]] = item
    return list(result.values())


def _ordered_unique(values: list[Any]) -> list[Any]:
    result = []
    seen = set()
    for value in values:
        if value in (None, "") or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _split_correction_notes(text: str) -> list[str]:
    chunks = re.split(r"[\n；;]+", text)
    notes = [chunk.strip(" -\t。") for chunk in chunks if chunk.strip(" -\t。")]
    return notes or ([text.strip()] if text.strip() else [])


def _stable_id(prefix: str, *parts: Any) -> str:
    raw = "|".join(str(part) for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def _norm(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "").replace("_", "")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
