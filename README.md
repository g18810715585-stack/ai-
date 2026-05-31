# AI Meta Agent

## 当前面板使用

1. 双击 `open-panel.cmd` 打开本地面板。
2. 在“飞书规划链接”里粘贴这次活动的飞书规划文档或表格链接。
3. 可选：在“价值表飞书链接”里粘贴基础价值表链接。工具会按商品名把规划表里的商品匹配到“奖励类型 / 内容ID / 数量”，并把结果带入分析和 AI 草案上下文。
4. 在“配置表目录”里填写本地配置表根目录。这个输入会自动记住上次填写的路径。
5. 点击“扫描配置目录”，工具会按 Excel 的 sheet 页名称识别配置表，并排除说明页、空表等明显不是数据表的 sheet。
6. 点击“选择配置表”，在弹出的面板里勾选这次活动涉及的几张主要关联表。没有扫描结果时，可以先在“常用表列表”里粘贴 sheet 名并保存。
7. 点击“分析表格”，确认识别结果和商品匹配结果；再点击“生成草案”，让 AI 基于所选多张表分析字段和可能的主外键关系。

面板已经不再提供“规划表 Excel”和“单张配置表 Excel”两个上传入口。配置表以目录扫描为主，规划表以飞书链接为主。
默认常用表来自 [config/common-tables.json](config/common-tables.json)，里面只保存符合数据表命名规范的 sheet 名，不保存本机真实 Excel 路径。

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
2. 上传“规划表 Excel”，或在“飞书规划链接”里粘贴飞书文档/知识库表格/电子表格链接。
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

接入真实 AI 时，在项目根目录新建本地 `.env`（不要提交 Git），二选一或都填：

```text
# ChatGPT / Gemini / Claude / DeepSeek 都走公司 BI
# BASEAI_API_KEY 填你的公司 BI Key
BASEAI_BASE_URL=https://baseai.rivergame.net/v1
CHATGPT_MODEL=gpt-5.5
GEMINI_MODEL=gemini-3.1-pro-preview
CLAUDE_MODEL=claude-opus-4-8
DEEPSEEK_MODEL=deepseek-v4-pro
```

实际 `.env` 里需要在 `BASEAI_API_KEY` 后面填入公司 BI Key；四个服务商都会使用这个 Key。

面板里“草案生成方式”保持“本地草案”时不会调用模型；切到“真实 AI”后，可在旁边选择 `ChatGPT`、`Gemini`、`Claude`、`DeepSeek`。命令行模式通过 manifest 的 `ai.provider` 控制，支持 `chatgpt`、`gemini`、`claude`、`deepseek_v4_pro`；旧的 `baseai` 会兼容为 `chatgpt`。

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

`open-panel.cmd` 会启动本地服务并自动打开浏览器。使用面板时请保持这个命令窗口打开；关闭窗口就会停止本地服务。

如果使用了旧的后台启动方式，或需要清理残留的本地服务，可以运行：

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

## 经验教学

经验教学分三步使用：

1. 在面板“经验录入”里写一条自然语言规则，然后点“AI 整理经验”。工具会先把口语化经验整理成可编辑文本，不会立刻保存。
2. 检查“整理结果”，必要时手动改几句，再点“保存整理结果”。经验会保存到本地 `.knowledge`，默认不进 Git。
3. 需要回看或维护经验时，点“查看历史经验”，可以按录入时间查看、搜索、修改或删除经验。
4. 填好飞书规划链接、配置表目录，并选择这次活动的主要目标配置表后，点“识别活动模板”。工具会输出“配表计划”和“待确认字段”。
5. 确认计划后再点“分析关联关系”和“生成草案”。草案只会生成待审核 Patch，低置信字段会进“待确认字段”，不会硬写。

CLI 也可以录入经验和生成配表计划：

```powershell
node src/cli.mjs teach --manifest fixtures/sample.manifest.json --text "兑换商店活动一般要看 activity、active_shop、exchange、reward、goods、key"
node src/cli.mjs experience-summary --manifest fixtures/sample.manifest.json --text "规划里商品名通常对应 goods.name，价格对应 exchange.price"
node src/cli.mjs experience-list --manifest fixtures/sample.manifest.json
node src/cli.mjs plan --manifest fixtures/sample.manifest.json
```

知识库文件分开保存在 `.knowledge/rules.jsonl`、`.knowledge/activity_templates.jsonl`、`.knowledge/field_mappings.jsonl` 和 `.knowledge/case_examples.jsonl`。审核草案后运行 `learn` 会同时记录习惯和案例证据，后续相似活动会优先复用。

## CLI

```text
server   启动本地网页面板
analyze  读取 manifest，生成 Workbook IR 和最小 AI 上下文
schema-scan  扫描配置表目录，生成 Schema 草案和配置 sheet 报告
relations  分析已选目标表的一跳/二跳关联关系
teach    写入一条自然语言配表经验到本地知识库
experience-summary  先用 AI/本地规则整理经验，生成可审核文本
experience-list / experience-update / experience-delete  管理历史经验
plan     识别活动模板并生成配表计划
draft    生成配置 patch，可调用公司 BI，也可使用 --stub 本地草案
apply    执行 patch，生成 preview、diff、validation、rollback
learn    把人工确认或修正沉淀为习惯记录
```

## 飞书规划链接

面板里的“飞书规划链接”可以直接作为规划表输入：

- 飞书电子表格或知识库里的表格链接会通过 `lark-cli sheets +read` 读取为 Workbook IR。
- 普通飞书文档链接会通过 `lark-cli docs +fetch --api-version v2` 读取为文本规划 sheet，供后续 AI 草案使用。
- “价值表飞书链接”会作为 `item_base` 来源读取，支持表头别名 `商品名称 / 商品名 / 道具名`、`奖励类型 / type_1`、`内容ID / 道具ID / reward_1`、`数量 / num_1`。分析时会生成 `planning-item-resolution.json`。
- 本地只读取飞书内容，不写回飞书，也不会覆盖远端文档。
- 需要本机能找到 `lark-cli`，可以放在 `lark-cli-bin/lark-cli.exe`，或通过 `LARK_CLI_PATH` 指定路径，并提前完成用户授权。

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
