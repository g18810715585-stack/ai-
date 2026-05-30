from __future__ import annotations

import shutil
from dataclasses import dataclass


@dataclass
class FeishuReadResult:
    ok: bool
    message: str


def check_feishu_ready(url: str) -> FeishuReadResult:
    if "feishu.cn" not in url and "larksuite.com" not in url:
        return FeishuReadResult(False, "不是可识别的飞书/Lark 表格链接")
    if not shutil.which("lark-cli"):
        return FeishuReadResult(
            False,
            "已识别飞书链接，但本机未找到 lark-cli。请先安装并完成 sheets/wiki 读取授权，或改用本地 Excel。",
        )
    return FeishuReadResult(
        False,
        "已找到 lark-cli，但首版飞书适配器只负责输入校验；请先导出为本地 Excel，后续可接入 lark-cli 拉取。",
    )
