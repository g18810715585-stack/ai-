from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


DEFAULT_SHEET_RANGE = "A1:ZZ1000"


@dataclass
class FeishuReadResult:
    ok: bool
    message: str


@dataclass
class FeishuSourcePayload:
    kind: str
    title: str | None = None
    values: list[list[Any]] = field(default_factory=list)
    text: str = ""
    sheet_id: str | None = None
    value_range: str | None = None
    spreadsheet_token: str | None = None
    notices: list[str] = field(default_factory=list)


def is_feishu_url(url: str) -> bool:
    return "feishu.cn" in url or "larksuite.com" in url


def check_feishu_ready(url: str, base_dir: Path | None = None) -> FeishuReadResult:
    if not is_feishu_url(url):
        return FeishuReadResult(False, "不是可识别的飞书/Lark 链接")
    if not resolve_lark_cli(base_dir):
        return FeishuReadResult(
            False,
            "已识别飞书链接，但本机未找到 lark-cli。请先安装并完成 docs/sheets/wiki 读取授权，或改用本地 Excel。",
        )
    return FeishuReadResult(True, "飞书读取环境已就绪")


def resolve_lark_cli(base_dir: Path | None = None) -> str | None:
    candidates = [
        os.environ.get("LARK_CLI_PATH"),
        os.environ.get("FEISHU_CLI_PATH"),
        shutil.which("lark-cli"),
        shutil.which("lark-cli.exe"),
    ]
    if base_dir:
        base_dir = base_dir.resolve()
        candidates.extend(
            [
                str(base_dir / "lark-cli-bin" / "lark-cli.exe"),
                str(base_dir.parent / "lark-cli-bin" / "lark-cli.exe"),
                str(base_dir.parent.parent / "lark-cli-bin" / "lark-cli.exe"),
            ]
        )
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(Path(candidate))
        if candidate and shutil.which(candidate):
            return candidate
    return None


def read_feishu_source(url: str, base_dir: Path, *, sheet_id: str | None = None, range_name: str | None = None) -> FeishuSourcePayload:
    ready = check_feishu_ready(url, base_dir)
    if not ready.ok:
        raise RuntimeError(ready.message)
    if _looks_like_sheet_url(url):
        return read_feishu_sheet(url, base_dir, sheet_id=sheet_id, range_name=range_name)
    try:
        return read_feishu_sheet(url, base_dir, sheet_id=sheet_id, range_name=range_name)
    except RuntimeError as sheet_error:
        try:
            return read_feishu_doc(url, base_dir)
        except RuntimeError as doc_error:
            raise RuntimeError(f"飞书链接读取失败。表格读取错误：{sheet_error}；文档读取错误：{doc_error}") from doc_error


def read_feishu_sheet(url: str, base_dir: Path, *, sheet_id: str | None = None, range_name: str | None = None) -> FeishuSourcePayload:
    lark_cli = resolve_lark_cli(base_dir)
    if not lark_cli:
        raise RuntimeError("未找到 lark-cli")
    sheet_id = sheet_id or extract_sheet_id(url)
    range_name = range_name or DEFAULT_SHEET_RANGE
    reference = resolve_lark_sheet_reference(lark_cli, url, base_dir)
    args = ["sheets", "+read", "--as", "user", "--range", range_name]
    if reference["spreadsheet_token"]:
        args.extend(["--spreadsheet-token", reference["spreadsheet_token"]])
    else:
        args.extend(["--url", url])
    if sheet_id:
        args.extend(["--sheet-id", sheet_id])
    output = run_lark_cli(lark_cli, args, "planning sheet", base_dir)
    data = output.get("data") or output
    value_range = data.get("valueRange") or data.get("data", {}).get("valueRange") or {}
    values = value_range.get("values") or data.get("values") or data.get("data", {}).get("values")
    if not isinstance(values, list):
        raise RuntimeError("lark-cli 没有返回表格 values")
    return FeishuSourcePayload(
        kind="sheet",
        title=reference.get("title"),
        values=values,
        sheet_id=sheet_id,
        value_range=value_range.get("range") or data.get("range") or range_name,
        spreadsheet_token=reference.get("spreadsheet_token"),
        notices=[*reference.get("notices", []), *([output.get("_notice")] if output.get("_notice") else [])],
    )


def read_feishu_doc(url: str, base_dir: Path) -> FeishuSourcePayload:
    lark_cli = resolve_lark_cli(base_dir)
    if not lark_cli:
        raise RuntimeError("未找到 lark-cli")
    output = run_lark_cli(
        lark_cli,
        ["docs", "+fetch", "--api-version", "v2", "--doc", url, "--as", "user", "--doc-format", "markdown"],
        "planning doc",
        base_dir,
    )
    data = output.get("data") or output
    text = _first_text(data, ["markdown", "content", "text", "body", "xml"]) or _first_text(output, ["markdown", "content", "text", "body", "xml"])
    if not text:
        text = json.dumps(data, ensure_ascii=False)
    return FeishuSourcePayload(kind="doc", title=data.get("title") or output.get("title"), text=text, notices=[output.get("_notice")] if output.get("_notice") else [])


def resolve_lark_sheet_reference(lark_cli: str, url: str, base_dir: Path) -> dict[str, Any]:
    wiki_token = extract_path_token(url, "wiki")
    if not wiki_token:
        return {"spreadsheet_token": extract_path_token(url, "sheets"), "title": None, "notices": []}
    output = run_lark_cli(
        lark_cli,
        ["wiki", "spaces", "get_node", "--params", json.dumps({"token": wiki_token}), "--format", "json", "--as", "user"],
        "wiki node",
        base_dir,
    )
    node = output.get("data", {}).get("node") or output.get("node")
    if not node:
        raise RuntimeError("无法解析飞书知识库节点")
    if node.get("obj_type") != "sheet":
        raise RuntimeError(f"知识库节点类型是 {node.get('obj_type')}，不是 sheet")
    if not node.get("obj_token"):
        raise RuntimeError("知识库节点没有返回 obj_token")
    return {
        "spreadsheet_token": node["obj_token"],
        "title": node.get("title"),
        "notices": [output.get("_notice")] if output.get("_notice") else [],
    }


def run_lark_cli(lark_cli: str, args: list[str], label: str, cwd: Path) -> dict[str, Any]:
    result = subprocess.run(
        [lark_cli, *args],
        cwd=str(cwd),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=120,
        check=False,
    )
    raw = (result.stdout or result.stderr or "").strip()
    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"lark-cli {label} 返回了非 JSON 内容：{raw[:800]}") from exc
    if result.returncode != 0 or parsed.get("ok") is False:
        error = parsed.get("error") or {}
        message = error.get("message") or raw or f"exit code {result.returncode}"
        hint = f" Hint: {error.get('hint')}" if error.get("hint") else ""
        raise RuntimeError(f"无法通过 lark-cli 读取 {label}：{message}.{hint}")
    return parsed


def extract_sheet_id(url: str) -> str | None:
    try:
        query = parse_qs(urlparse(url).query)
        return (query.get("sheet") or [None])[0]
    except Exception:
        return None


def extract_path_token(raw_url: str, segment_name: str) -> str | None:
    try:
        segments = [item for item in urlparse(raw_url).path.split("/") if item]
    except Exception:
        return None
    try:
        index = segments.index(segment_name)
    except ValueError:
        return None
    return segments[index + 1] if index + 1 < len(segments) else None


def _looks_like_sheet_url(url: str) -> bool:
    parsed = urlparse(url)
    return "/sheets/" in parsed.path or "sheet=" in parsed.query


def _first_text(data: dict[str, Any], keys: list[str]) -> str | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None
