# AI Meta Agent

`ai-meta-agent` 是一个从零搭建的 AI 配表代理人。它读取数值规划表、原始配置表、字段字典和历史习惯，在本地生成可审核的配置 patch，并由确定性程序执行写入、diff、校验、备份和回滚。

首版目标：

- 本地网页面板 + CLI。
- 支持本地 Excel 和飞书链接输入。
- 使用公司 BI 网关，接口兼容 `/chat/completions`。
- 本地解析表格后，只把必要摘要、字段、候选行和习惯片段发给 AI。
- Schema 驱动，不把某个活动类型写死在代码里。
- 默认只写预览副本；覆盖原表必须人工确认并生成 rollback。

## 快速开始

日常使用最短路径：

1. 双击 `open-panel.cmd`，等待浏览器自动打开。
2. 上传“规划表 Excel”。
3. 在“配置表目录”里填你的本地配置表根目录，例如 `C:\TopHero\Meta\meta_local`。工具会递归扫描目录里的 `.xlsx/.xlsm`，但配置表身份以 sheet 页名称为准，不按 Excel 文件名判断。
4. 如果只是临时测试单张表，也可以上传“单张配置表 Excel”，并确认“目标配置表名”，例如 `shop_pack_config`。
5. 第一次接入真实项目时，先点击“扫描配置目录”，生成 `schema-draft.json` 和配置表扫描报告。
6. 点击“分析表格”，检查工具识别到的 sheet、表头、隐藏列、合并单元格和配置表目录匹配结果。
7. 点击“生成草案”，查看“变更 Patch”里的新增/更新/删除建议。
8. 确认 patch 没问题后，点击“生成预览”，工具会生成预览 Excel、diff、校验报告和 rollback patch。
9. 如果这次结果符合你的配表习惯，点击“记录习惯”。
10. 用完后双击 `stop-panel.cmd`，关闭后台本地服务和端口。

第一轮试用可以先点面板里的“示例”，再按“扫描配置目录 → 分析表格 → 生成草案 → 生成预览 → 记录习惯”的顺序走一遍。

生成示例 Excel：

```powershell
python scripts/create_fixtures.py
```

分析示例规划表：

```powershell
node src/cli.mjs analyze --manifest fixtures/sample.manifest.json
```

生成 AI 草案。没有 `BASEAI_API_KEY` 时建议先用 stub：

```powershell
node src/cli.mjs draft --manifest fixtures/sample.manifest.json --stub
```

应用 patch 到预览副本：

```powershell
node src/cli.mjs apply --manifest fixtures/sample.manifest.json --patch .runs/latest/patch.json
```

启动本地面板：

```powershell
node src/cli.mjs server --port 4321
```

Windows 也可以直接启动面板：

```powershell
.\open-panel.cmd
```

`open-panel.cmd` 会在后台隐藏启动本地服务，并在健康检查通过后自动打开浏览器。使用完面板后可以停止本地服务：

```powershell
.\stop-panel.cmd
```

如果面板打不开，想在当前终端看服务日志，可以运行：

```powershell
.\run-panel.cmd
```

检查面板是否正在监听：

```powershell
.\check-panel.cmd
```

打开：

```text
http://127.0.0.1:4321
```

## CLI

```text
server   启动本地网页面板
analyze  读取 manifest，生成 Workbook IR 和最小 AI 上下文
schema-scan  扫描配置表目录，生成 Schema 草案和配置 sheet 报告
draft    生成配置 patch，可调用公司 BI，也可使用 --stub 本地草案
apply    执行 patch，生成 preview、diff、validation、rollback
learn    把人工确认或修正沉淀为习惯记录
```

## 数据边界

工具不会默认把整张真实 Excel 发给 AI。`draft` 会先在本地生成 `ai-context.json`，其中只包含：

- 表格结构摘要。
- 命中的字段别名和候选数据行。
- Schema 中允许 AI 看到的字段约束。
- 与当前场景相关的习惯片段。

真实 Excel、运行输出、习惯库和本地 Key 默认不提交到 Git。

## 配置表发现规则

- 只按 sheet 页名称匹配 Schema 里的表名或 `sheet` 配置。
- 不用 Excel 文件名兜底匹配，避免 `shop_pack_config.xlsx` 里没有同名 sheet 时误判。
- 扫描时会跳过明显不是数据表的 sheet，例如 `说明`、`目录`、`备注`、`示例`、`模板`、`更新记录`、`Sheet1`、`README` 等。
- “分析表格”的结果里会输出 `config_discovery`，其中包含已匹配表、未匹配表和被跳过的 sheet。
- “扫描配置目录”会输出 `schema-draft.json`，包含所有数据 sheet 的字段、类型推断、疑似主键、样例行和疑似关联字段。

## 目录

```text
ai_meta_agent/       Python 核心：Excel IR、Schema、Patch、Diff、Validation、Habit
src/                 Node CLI、本地 HTTP 服务和网页面板
config/              示例 Schema
fixtures/            示例 manifest；Excel 文件由脚本生成，不提交真实表
scripts/             本地辅助脚本
tests/               unittest 测试
```

## 安全规则

- AI 只生成 patch，不直接写生产 Excel。
- patch 里的每个操作必须包含来源、原因、置信度和风险等级。
- 低置信度、高风险、大量删除/覆盖会进入人工确认。
- 覆盖原表前必须有备份、diff、validation report 和 rollback patch。
- 飞书适配器只负责读取输入，不负责写回飞书或覆盖远端表。
