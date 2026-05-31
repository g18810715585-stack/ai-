from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


DEFAULT_SHEET_RANGE = "A1:ZZ1000"
FEISHU_PAYLOAD_LIMIT_MARKERS = ("data exceeded", "10485760")
FEISHU_INITIAL_CHUNK_ROWS = 500
FEISHU_MIN_CHUNK_ROWS = 50
_A1_RANGE_RE = re.compile(r"^\s*([A-Za-z]+)(\d+):([A-Za-z]+)(\d+)\s*$")


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
    try:
        values, value_range, notices = _read_feishu_sheet_values(lark_cli, url, base_dir, reference, sheet_id, range_name)
    except RuntimeError as exc:
        if not _is_payload_limit_error(exc):
            raise
        try:
            values, value_range, notices = _read_feishu_sheet_in_chunks(lark_cli, url, base_dir, reference, sheet_id, range_name)
        except RuntimeError as chunk_error:
            raise RuntimeError(f"{exc}；分块读取仍失败：{chunk_error}") from chunk_error
    return FeishuSourcePayload(
        kind="sheet",
        title=reference.get("title"),
        values=values,
        sheet_id=sheet_id,
        value_range=value_range or range_name,
        spreadsheet_token=reference.get("spreadsheet_token"),
        notices=_dedupe_notices([*reference.get("notices", []), *notices]),
    )


def _read_feishu_sheet_values(
    lark_cli: str,
    url: str,
    base_dir: Path,
    reference: dict[str, Any],
    sheet_id: str | None,
    range_name: str,
) -> tuple[list[list[Any]], str | None, list[str]]:
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
    values = value_range.get("values")
    if values is None:
        values = data.get("values")
    if values is None:
        values = data.get("data", {}).get("values")
    if not isinstance(values, list):
        raise RuntimeError("lark-cli 没有返回表格 values")
    notices = [output.get("_notice")] if output.get("_notice") else []
    return values, value_range.get("range") or data.get("range") or range_name, notices


def _read_feishu_sheet_in_chunks(
    lark_cli: str,
    url: str,
    base_dir: Path,
    reference: dict[str, Any],
    sheet_id: str | None,
    range_name: str,
) -> tuple[list[list[Any]], str | None, list[str]]:
    parsed = _parse_a1_range(range_name)
    if not parsed:
        raise RuntimeError(f"读取范围 {range_name} 不是 A1:Z100 形式，无法自动分块")
    start_row = parsed["start_row"]
    end_row = parsed["end_row"]
    if end_row < start_row:
        raise RuntimeError(f"读取范围 {range_name} 的结束行小于起始行")

    row = start_row
    chunk_rows = min(FEISHU_INITIAL_CHUNK_ROWS, end_row - start_row + 1)
    rows_by_number: dict[int, list[Any]] = {}
    notices: list[str] = ["飞书单次读取超过 10MB，已自动按行分块读取。"]
    chunk_count = 0
    last_value_range: str | None = None
    while row <= end_row:
        chunk_end = min(end_row, row + chunk_rows - 1)
        chunk_range = _format_a1_range(parsed, row, chunk_end)
        try:
            values, actual_range, chunk_notices = _read_feishu_sheet_values(lark_cli, url, base_dir, reference, sheet_id, chunk_range)
        except RuntimeError as exc:
            if _is_payload_limit_error(exc) and chunk_rows > FEISHU_MIN_CHUNK_ROWS:
                chunk_rows = max(FEISHU_MIN_CHUNK_ROWS, chunk_rows // 2)
                continue
            raise

        chunk_count += 1
        last_value_range = actual_range or chunk_range
        notices.extend(chunk_notices)
        actual_start_row = _range_start_row(actual_range) or row
        for offset, value_row in enumerate(values):
            rows_by_number[actual_start_row + offset] = value_row
        row = chunk_end + 1

    if rows_by_number:
        merged_values = [rows_by_number.get(index, []) for index in range(start_row, max(rows_by_number) + 1)]
    else:
        merged_values = []
    notices.append(f"分块读取完成：{chunk_count} 段，范围 {range_name}。")
    return merged_values, f"{range_name} (chunked, last={last_value_range})", _dedupe_notices(notices)


def _is_payload_limit_error(error: Exception) -> bool:
    message = str(error).lower()
    return all(marker in message for marker in FEISHU_PAYLOAD_LIMIT_MARKERS)


def _parse_a1_range(range_name: str) -> dict[str, Any] | None:
    prefix = ""
    cell_range = range_name.strip()
    if "!" in cell_range:
        prefix, cell_range = cell_range.rsplit("!", 1)
        prefix = f"{prefix}!"
    match = _A1_RANGE_RE.match(cell_range)
    if not match:
        return None
    start_col, start_row, end_col, end_row = match.groups()
    return {
        "prefix": prefix,
        "start_col": start_col.upper(),
        "start_row": int(start_row),
        "end_col": end_col.upper(),
        "end_row": int(end_row),
    }


def _format_a1_range(parsed: dict[str, Any], start_row: int, end_row: int) -> str:
    return f"{parsed['prefix']}{parsed['start_col']}{start_row}:{parsed['end_col']}{end_row}"


def _range_start_row(range_name: str | None) -> int | None:
    if not range_name:
        return None
    parsed = _parse_a1_range(range_name)
    if parsed:
        return int(parsed["start_row"])
    prefix = range_name.split(":", 1)[0]
    match = re.search(r"(\d+)$", prefix)
    return int(match.group(1)) if match else None


def _dedupe_notices(notices: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for notice in notices:
        text = str(notice).strip() if notice else ""
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


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
