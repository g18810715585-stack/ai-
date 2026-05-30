from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import PatternFill

from ai_meta_agent.cli import analyze_manifest
from ai_meta_agent.draft import call_baseai, make_stub_patch
from ai_meta_agent.feishu import FeishuSourcePayload
from ai_meta_agent.habits import append_habit, habit_from_patch, load_habits, match_habits
from ai_meta_agent.io_utils import read_json, write_json
from ai_meta_agent.models import Manifest, PlanningSource
from ai_meta_agent.patch_engine import apply_patch
from ai_meta_agent.schema import load_schema
from ai_meta_agent.schema_scanner import scan_config_schema
from ai_meta_agent.workbook_ir import load_source_ir


ROOT = Path(__file__).resolve().parents[1]


def make_planning(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "礼包规划"
    sheet.merge_cells("A1:F1")
    sheet["A1"] = "六月礼包"
    headers = ["礼包ID", "礼包名称", "价格ID", "限购次数", "开始时间", "结束时间"]
    for col, header in enumerate(headers, start=1):
        sheet.cell(2, col).value = header
    sheet.append([1001, "每日礼包", 68, None, "2026-06-01 05:00:00", "2026-06-08 04:59:59"])
    sheet.append([1002, "进阶礼包", 128, 1, "2026-06-01 05:00:00", "2026-06-08 04:59:59"])
    sheet["B4"].fill = PatternFill(fill_type="solid", fgColor="FFF2CC")
    sheet["F4"].comment = Comment("示例备注", "test")
    sheet.column_dimensions["G"].hidden = True
    sheet["G2"] = "隐藏列"
    workbook.save(path)


def make_config(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "shop_pack_config"
    headers = [
        "pack_id",
        "name",
        "price_id",
        "limit_type",
        "limit_count",
        "start_time",
        "end_time",
        "creator",
        "create_time",
        "internal_note",
    ]
    sheet.append(headers)
    sheet.append([1001, "旧每日礼包", 30, "daily", 1, "old-start", "old-end", "gaoyang", "2026-05-01", "keep"])
    reward = workbook.create_sheet("reward_item_config")
    reward.append(["reward_group_id", "item_id", "item_count", "item_order"])
    reward.append([1001, 3001, 10, 1])
    workbook.save(path)


def make_manifest(tmp: Path, planning: Path, config: Path) -> Path:
    manifest = {
        "project": "unit-sample",
        "mode": "supervised_write",
        "schema_path": str(ROOT / "config" / "example.schema.json"),
        "run_root": str(tmp / ".runs"),
        "planning_sources": [{"id": "plan", "kind": "local_excel", "path": str(planning), "role": "planning"}],
        "config_tables": {
            "shop_pack_config": {"path": str(config), "sheet": "shop_pack_config"},
            "reward_item_config": {"path": str(config), "sheet": "reward_item_config"},
        },
        "habit_store": str(tmp / ".knowledge" / "habits.jsonl"),
    }
    path = tmp / "manifest.json"
    write_json(path, manifest)
    return path


class WorkflowTests(unittest.TestCase):
    def test_workbook_ir_and_stub_patch_flow(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            planning = tmp / "planning.xlsx"
            config = tmp / "config.xlsx"
            make_planning(planning)
            make_config(config)
            manifest_path = make_manifest(tmp, planning, config)

            manifest, schema, run_dir, context = analyze_manifest(manifest_path, tmp, "analysis")
            self.assertTrue((run_dir / "analysis.json").exists())
            sheet = context["workbooks"][0]["sheets"][0]
            self.assertEqual(sheet["header_row"], 2)
            self.assertIn("A1:F1", sheet["merged_ranges"])
            self.assertIn("G", sheet["hidden_columns"])

            patch = make_stub_patch(manifest, schema, context, str(tmp))
            self.assertEqual(len(patch.operations), 2)
            self.assertEqual([op.op for op in patch.operations], ["update", "insert"])
            self.assertTrue(all(op.needs_confirmation for op in patch.operations))

            apply_dir = tmp / ".runs" / "apply-test"
            apply_dir.mkdir(parents=True)
            result = apply_patch(manifest, schema, patch, tmp, apply_dir)
            self.assertTrue(result["previews"])
            preview = Path(next(iter(result["previews"].values())))
            self.assertTrue(preview.exists())
            workbook = load_workbook(preview, data_only=True)
            sheet = workbook["shop_pack_config"]
            rows = list(sheet.iter_rows(values_only=True))
            self.assertEqual(rows[1][1], "每日礼包")
            self.assertEqual(rows[1][7], "gaoyang")
            self.assertEqual(rows[2][0], 1002)
            validation = next(iter(result["validation"].values()))
            self.assertEqual(validation["errors"], [])
            self.assertTrue(result["rollback_patch"]["operations"])

    def test_habit_learning_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            planning = tmp / "planning.xlsx"
            config = tmp / "config.xlsx"
            make_planning(planning)
            make_config(config)
            manifest_path = make_manifest(tmp, planning, config)
            manifest = Manifest.model_validate(json.loads(manifest_path.read_text(encoding="utf-8")))
            schema = load_schema(ROOT / "config" / "example.schema.json")
            _, _, _, context = analyze_manifest(manifest_path, tmp, "analysis")
            patch = make_stub_patch(manifest, schema, context, str(tmp))
            habit = habit_from_patch(patch, "accepted", "unit test accepted")
            habit_path = tmp / ".knowledge" / "habits.jsonl"
            append_habit(habit_path, habit)
            habits = load_habits(habit_path)
            self.assertEqual(len(habits), 1)
            matched = match_habits(habits, "unit-sample", ["shop_pack_config"])
            self.assertEqual(matched[0].habit_id, habit.habit_id)

    def test_config_root_discovers_tables(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            planning = tmp / "planning.xlsx"
            config_dir = tmp / "configs"
            config_dir.mkdir()
            config = config_dir / "tables.xlsx"
            misleading = config_dir / "shop_pack_config.xlsx"
            make_planning(planning)
            make_config(config)
            misleading_workbook = Workbook()
            misleading_sheet = misleading_workbook.active
            misleading_sheet.title = "说明"
            misleading_sheet["A1"] = "这个文件名像配置表，但 sheet 不是数据表"
            misleading_workbook.save(misleading)
            manifest = {
                "project": "root-sample",
                "mode": "supervised_write",
                "schema_path": str(ROOT / "config" / "example.schema.json"),
                "run_root": str(tmp / ".runs"),
                "planning_sources": [{"id": "plan", "kind": "local_excel", "path": str(planning), "role": "planning"}],
                "config_roots": [{"path": str(config_dir), "recursive": True}],
                "habit_store": str(tmp / ".knowledge" / "habits.jsonl"),
            }
            manifest_path = tmp / "manifest-root.json"
            write_json(manifest_path, manifest)

            manifest_model, schema, _, context = analyze_manifest(manifest_path, tmp, "analysis")
            self.assertIn("shop_pack_config", manifest_model.config_tables)
            self.assertIn("reward_item_config", manifest_model.config_tables)
            self.assertEqual(context["config_discovery"]["matched"]["shop_pack_config"]["source"], "sheet_name")
            self.assertTrue(any(item["name"] == "说明" for item in context["config_discovery"]["skipped_sheets"]))
            patch = make_stub_patch(manifest_model, schema, context, str(tmp))
            self.assertEqual([op.op for op in patch.operations], ["update", "insert"])

    def test_config_root_does_not_match_by_file_name(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            planning = tmp / "planning.xlsx"
            config_dir = tmp / "configs"
            config_dir.mkdir()
            make_planning(planning)
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Sheet1"
            sheet.append(["pack_id", "name"])
            sheet.append([1001, "文件名不能代表表名"])
            workbook.save(config_dir / "shop_pack_config.xlsx")
            manifest = {
                "project": "file-name-is-not-table",
                "mode": "supervised_write",
                "schema_path": str(ROOT / "config" / "example.schema.json"),
                "run_root": str(tmp / ".runs"),
                "planning_sources": [{"id": "plan", "kind": "local_excel", "path": str(planning), "role": "planning"}],
                "config_roots": [{"path": str(config_dir), "recursive": True}],
                "habit_store": str(tmp / ".knowledge" / "habits.jsonl"),
            }
            manifest_path = tmp / "manifest-root.json"
            write_json(manifest_path, manifest)

            manifest_model, _, _, context = analyze_manifest(manifest_path, tmp, "analysis")
            self.assertNotIn("shop_pack_config", manifest_model.config_tables)
            self.assertIn("shop_pack_config", context["config_discovery"]["unmatched_tables"])

    def test_schema_scan_builds_schema_draft_from_sheet_names(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            config_dir = tmp / "configs"
            config_dir.mkdir()
            config = config_dir / "multi.xlsx"
            make_config(config)
            workbook = load_workbook(config)
            workbook["shop_pack_config"]["F2"] = datetime(2026, 6, 1, 5, 0, 0)
            note = workbook.create_sheet("说明")
            note["A1"] = "非数据页"
            workbook.save(config)
            manifest = Manifest.model_validate(
                {
                    "project": "schema-scan-sample",
                    "mode": "supervised_write",
                    "schema_path": str(ROOT / "config" / "example.schema.json"),
                    "run_root": str(tmp / ".runs"),
                    "planning_sources": [{"id": "dummy", "kind": "local_excel", "path": str(config), "role": "planning"}],
                    "config_roots": [{"path": str(config_dir), "recursive": True}],
                    "habit_store": str(tmp / ".knowledge" / "habits.jsonl"),
                }
            )
            run_dir = tmp / ".runs" / "schema-scan"
            run_dir.mkdir(parents=True)
            result = scan_config_schema(manifest, tmp, run_dir)
            schema_draft = result["schema_draft"]
            report = result["report"]
            self.assertIn("shop_pack_config", schema_draft["tables"])
            self.assertIn("reward_item_config", schema_draft["tables"])
            self.assertIn("pack_id", schema_draft["tables"]["shop_pack_config"]["fields"])
            self.assertTrue(any(item["name"] == "说明" for item in report["skipped_sheets"]))
            self.assertTrue((run_dir / "schema-draft.json").exists())
            saved_report = read_json(run_dir / "schema-scan.json")
            self.assertEqual(saved_report["tables"]["shop_pack_config"]["sample_rows"][0]["start_time"], "2026-06-01T05:00:00")

    def test_feishu_sheet_source_becomes_workbook_ir(self) -> None:
        source = PlanningSource(id="plan", kind="feishu", url="https://rivergame.feishu.cn/wiki/demo?sheet=abc", role="planning")
        payload = FeishuSourcePayload(kind="sheet", title="飞书规划表", values=[["礼包ID", "礼包名称"], [1001, "每日礼包"]])
        with tempfile.TemporaryDirectory() as raw, patch("ai_meta_agent.workbook_ir.read_feishu_source", return_value=payload) as reader:
            workbook = load_source_ir(source, Path(raw))
        reader.assert_called_once()
        self.assertEqual(workbook.source_id, "plan")
        self.assertEqual(workbook.sheets[0].name, "飞书规划表")
        self.assertEqual(workbook.sheets[0].header_row, 1)
        self.assertEqual(workbook.sheets[0].sample_rows[0]["礼包ID"], 1001)

    def test_feishu_doc_source_becomes_text_sheet(self) -> None:
        source = PlanningSource(id="doc", kind="feishu", url="https://rivergame.feishu.cn/docx/demo", role="planning")
        payload = FeishuSourcePayload(kind="doc", title="活动规划", text="活动时间：6月1日\n奖励：金币")
        with tempfile.TemporaryDirectory() as raw, patch("ai_meta_agent.workbook_ir.read_feishu_source", return_value=payload):
            workbook = load_source_ir(source, Path(raw))
        sheet = workbook.sheets[0]
        self.assertEqual(sheet.name, "活动规划")
        self.assertEqual(sheet.headers[:2], ["section", "content"])
        self.assertIn("活动时间", sheet.sample_rows[0]["content"])

    def test_company_bi_model_provider_choices_share_baseai_endpoint(self) -> None:
        response_payload = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "patch_id": "patch_company_bi",
                                "project": "provider-sample",
                                "mode": "supervised_write",
                                "operations": [],
                                "generated_by": "ai-meta-agent",
                            }
                        )
                    }
                }
            ]
        }
        captured = []

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps(response_payload).encode("utf-8")

        def fake_urlopen(request, timeout):
            captured.append({"url": request.full_url, "body": json.loads(request.data.decode("utf-8"))})
            return FakeResponse()

        providers = {
            "baseai": "gpt-5.5",
            "gemini": "gemini-3.1-pro-preview",
            "claude": "claude-opus-4-8",
        }
        with patch.dict(os.environ, {"BASEAI_API_KEY": "unit-key"}, clear=True):
            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                for provider in providers:
                    manifest = Manifest.model_validate(
                        {
                            "project": "provider-sample",
                            "mode": "supervised_write",
                            "schema_path": str(ROOT / "config" / "example.schema.json"),
                            "planning_sources": [{"id": "plan", "kind": "local_excel", "path": "dummy.xlsx", "role": "planning"}],
                            "ai": {"provider": provider},
                        }
                    )
                    generated = call_baseai(manifest, {"project": "provider-sample"})
                    self.assertEqual(generated.patch_id, "patch_company_bi")

        self.assertEqual([item["body"]["model"] for item in captured], list(providers.values()))
        self.assertTrue(all(item["url"] == "https://baseai.rivergame.net/v1/chat/completions" for item in captured))
        self.assertIn("temperature", captured[0]["body"])
        self.assertIn("temperature", captured[1]["body"])
        self.assertNotIn("temperature", captured[2]["body"])

    def test_deepseek_provider_uses_company_bi_request(self) -> None:
        manifest = Manifest.model_validate(
            {
                "project": "deepseek-sample",
                "mode": "supervised_write",
                "schema_path": str(ROOT / "config" / "example.schema.json"),
                "planning_sources": [{"id": "plan", "kind": "local_excel", "path": "dummy.xlsx", "role": "planning"}],
                "ai": {"provider": "deepseek_v4_pro"},
            }
        )
        response_payload = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "patch_id": "patch_deepseek",
                                "project": "deepseek-sample",
                                "mode": "supervised_write",
                                "operations": [],
                                "generated_by": "ai-meta-agent",
                            }
                        )
                    }
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }
        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps(response_payload).encode("utf-8")

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            captured["body"] = json.loads(request.data.decode("utf-8"))
            captured["authorization"] = request.headers.get("Authorization")
            return FakeResponse()

        with tempfile.TemporaryDirectory() as raw:
            raw_response = Path(raw) / "ai-response.json"
            with patch.dict(os.environ, {"BASEAI_API_KEY": "unit-key"}, clear=True):
                with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                    generated = call_baseai(manifest, {"project": "deepseek-sample"}, raw_response)
            self.assertTrue(raw_response.exists())

        self.assertEqual(generated.patch_id, "patch_deepseek")
        self.assertEqual(captured["url"], "https://baseai.rivergame.net/v1/chat/completions")
        self.assertEqual(captured["body"]["model"], "deepseek-v4-pro")
        self.assertNotIn("thinking", captured["body"])
        self.assertEqual(captured["body"]["response_format"], {"type": "json_object"})
        self.assertEqual(captured["authorization"], "Bearer unit-key")

    def test_deepseek_provider_requires_company_bi_key(self) -> None:
        manifest = Manifest.model_validate(
            {
                "project": "deepseek-sample",
                "mode": "supervised_write",
                "schema_path": str(ROOT / "config" / "example.schema.json"),
                "planning_sources": [{"id": "plan", "kind": "local_excel", "path": "dummy.xlsx", "role": "planning"}],
                "ai": {"provider": "deepseek-v4-pro"},
            }
        )
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "BASEAI_API_KEY"):
                call_baseai(manifest, {})


if __name__ == "__main__":
    unittest.main()
