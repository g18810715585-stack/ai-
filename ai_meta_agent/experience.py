from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import Manifest, Patch, SchemaBundle, WorkbookIR


KNOWLEDGE_FILES = {
    "rules": "rules.jsonl",
    "activity_templates": "activity_templates.jsonl",
    "field_mappings": "field_mappings.jsonl",
    "case_examples": "case_examples.jsonl",
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
    return {
        "rules": _load_jsonl(root / KNOWLEDGE_FILES["rules"]),
        "activity_templates": [*DEFAULT_ACTIVITY_TEMPLATES, *_load_jsonl(root / KNOWLEDGE_FILES["activity_templates"])],
        "field_mappings": [*DEFAULT_FIELD_MAPPINGS, *_load_jsonl(root / KNOWLEDGE_FILES["field_mappings"])],
        "case_examples": _load_jsonl(root / KNOWLEDGE_FILES["case_examples"]),
    }


def teach_experience(base_dir: Path, project: str, text: str, source: str = "manual") -> dict[str, Any]:
    root = knowledge_dir(base_dir)
    root.mkdir(parents=True, exist_ok=True)
    now = _now()
    text = text.strip()
    if not text:
        raise ValueError("经验内容不能为空")

    records = parse_experience_text(project, text, source=source, timestamp=now)
    for kind, items in records.items():
        path = root / KNOWLEDGE_FILES[kind]
        for item in items:
            _append_jsonl(path, item)
    return {
        "store": str(root),
        "created": {kind: len(items) for kind, items in records.items()},
        "records": records,
    }


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

    templates = []
    for template in DEFAULT_ACTIVITY_TEMPLATES:
        if any(_norm(alias) in normalized for alias in template["aliases"]):
            item = dict(template)
            item["template_id"] = _stable_id("template", project, template["template_id"], text)
            item["project"] = project
            item["source"] = source
            item["confidence"] = min(0.95, float(item.get("confidence", 0.65)) + 0.08)
            item["evidence"] = [*item.get("evidence", []), text[:120]]
            item["created_at"] = timestamp
            templates.append(item)

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
        "activity_templates": _dedupe_records(templates, "template_id"),
        "field_mappings": _dedupe_records(mappings, "mapping_id"),
        "case_examples": [],
    }


def build_experience_context(
    base_dir: Path,
    manifest: Manifest,
    schema: SchemaBundle,
    workbooks: list[WorkbookIR],
    relationship_map: dict[str, Any],
) -> dict[str, Any]:
    store = load_experience(base_dir)
    signals = planning_signals(workbooks)
    target_tables = set(schema.tables.keys())
    templates = _match_templates(store["activity_templates"], signals, target_tables)
    field_mappings = _match_field_mappings(store["field_mappings"], signals, target_tables, schema)
    rules = _match_rules(store["rules"], manifest.project, signals, target_tables)
    cases = _match_cases(store["case_examples"], manifest.project, signals, target_tables)
    plan = build_config_plan(manifest, schema, relationship_map, templates, field_mappings, rules, cases, signals)
    return {
        "matched_activity_templates": templates[:5],
        "matched_field_mappings": field_mappings[:40],
        "matched_rules": rules[:20],
        "similar_cases": cases[:8],
        "config_plan": plan,
        "knowledge_counts": {key: len(value) for key, value in store.items()},
    }


def build_config_plan(
    manifest: Manifest,
    schema: SchemaBundle,
    relationship_map: dict[str, Any],
    templates: list[dict[str, Any]],
    field_mappings: list[dict[str, Any]],
    rules: list[dict[str, Any]],
    cases: list[dict[str, Any]],
    signals: dict[str, Any],
) -> dict[str, Any]:
    top_template = templates[0] if templates else None
    current_targets = list(schema.tables.keys())
    template_tables = top_template.get("target_tables", []) if top_template else []
    recommended = _ordered_unique([
        *template_tables,
        *relationship_map.get("recommended_tables", []),
        *[table for mapping in field_mappings for table in [mapping.get("target_table")] if table],
    ])
    missing = []
    if not top_template:
        missing.append("未识别出明确活动模板，请补充活动类型或写入一条经验规则。")
    if not field_mappings:
        missing.append("规划表字段没有命中字段映射，请说明规划列名对应哪些配置表字段。")
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

    return {
        "activity_type": top_template.get("name") if top_template else "未识别",
        "activity_template_id": top_template.get("template_id") if top_template else None,
        "confidence": top_template.get("match_score", 0) if top_template else 0,
        "current_target_tables": current_targets,
        "recommended_target_tables": [table for table in recommended if table not in current_targets],
        "all_recommended_tables": recommended,
        "relation_chain": top_template.get("relation_chain", []) if top_template else [],
        "required_fields": top_template.get("required_fields", {}) if top_template else {},
        "matched_field_mappings": field_mappings[:40],
        "matched_rules": rules[:20],
        "similar_cases": cases[:8],
        "missing_information": missing,
        "pending_confirmations": pending[:40],
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


def planning_signals(workbooks: list[WorkbookIR]) -> dict[str, Any]:
    sheet_names: list[str] = []
    headers: list[str] = []
    sample_values: list[str] = []
    for workbook in workbooks:
        for sheet in workbook.sheets:
            sheet_names.append(sheet.name)
            headers.extend(str(header) for header in sheet.headers if str(header).strip())
            for row in sheet.sample_rows[:8]:
                sample_values.extend(str(value) for value in row.values() if str(value).strip())
    text = "\n".join([*sheet_names, *headers, *sample_values])
    return {
        "sheet_names": _ordered_unique(sheet_names),
        "headers": _ordered_unique(headers),
        "text": text,
        "normalized_text": _norm(text),
    }


def experience_context_payload(experience: dict[str, Any]) -> dict[str, Any]:
    return {
        "matched_activity_templates": experience.get("matched_activity_templates", []),
        "matched_field_mappings": experience.get("matched_field_mappings", []),
        "matched_rules": experience.get("matched_rules", []),
        "similar_cases": experience.get("similar_cases", []),
        "config_plan": experience.get("config_plan", {}),
    }


def _match_templates(templates: list[dict[str, Any]], signals: dict[str, Any], target_tables: set[str]) -> list[dict[str, Any]]:
    text = signals.get("normalized_text", "")
    scored = []
    for template in templates:
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
        note = _norm(case.get("note", ""))
        if note and note in text:
            score += 0.1
        if score >= 0.55 and (overlap or case.get("project") == project):
            item = dict(case)
            item["match_score"] = round(min(score, 0.98), 3)
            scored.append(item)
    return sorted(scored, key=lambda item: (-item["match_score"], item.get("created_at", "")))


def _parse_explicit_mappings(project: str, text: str, timestamp: str, source: str) -> list[dict[str, Any]]:
    mappings = []
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


def _stable_id(prefix: str, *parts: Any) -> str:
    raw = "|".join(str(part) for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def _norm(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "").replace("_", "")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
