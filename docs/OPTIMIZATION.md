# 优化方向分析（对话式 Excel 助手）

> 目标：用户通过**自然语言对话 + 可视化**处理 Excel，不写公式、不写 VBA、不写 Python。本方案面向**内网/离线**交付，因此所有方向均以「无外网依赖、可本机/内网部署、可审计」为约束。
>
> 现状结论：项目已完成「确定性的 13 类操作 + Univer 表格编辑器 + 受限 Agent（5 个 MCP 工具）」三层能力，底座扎实。优化主线是**把已经存在但未接线的能力（`data_toolkit`）释放出来，并补上「公式 / 图表 / 透视 / 更强的对话 Agent」四块关键缺口**。

---

## 1. 现状盘点（基于代码）

| 层 | 现状 | 关键位置 |
|---|---|---|
| 表格编辑 | Univer 0.25.1（开源自带插件），导入/导出走自研 JSON 快照，不直接读 xlsx | `gui/src/workbook/engine.ts`、`adapter.ts` |
| Excel 读写 | openpyxl 读、XlsxWriter 写、calamine 读 `.xls`、pywin32 原生重算 | `assistant/workbook_excel.py` |
| 数据操作 | 13 类确定性操作（append/join/clean/compare/group/melt/pivot/template/recalculate/calculate/classify/create_table/edit_workbook） | `assistant/models.py:40`、`assistant/tables.py` |
| 公式 | 白名单 36 函数，无数组公式/外部引用，循环检测 | `assistant/workbook_model.py:10` |
| 图表 / 透视表 / 条件格式 / 图片 / 批注 / 超链接 | **导入即进入只读**（preflight 拦截 `xl/charts/`、`xl/pivotTables/` 等） | `assistant/workbook_excel.py:213` |
| Agent | Qwen Code CLI 子进程 + 5 个 MCP 工具，deny-by-default 权限，`max_session_turns=20` | `assistant/agent.py`、`assistant/mcp_server.py` |
| 对话 UI | 文本框 + 场景快填 + 问题确认，非流式 | `gui/src/App.vue:174` |
| 沉睡能力 | `data_toolkit` 有 profiling / database(duckdb) / sql_runner / reporting / audit / validation / polars 引擎，**仅 4 个函数被接线** | `assistant/tables.py:11-13` vs `data_toolkit/` |
| 模型接入 | 仅 OpenAI 兼容端点（Qwen Code 走 `OPENAI_BASE_URL`），无本地推理矩阵、无 fallback | `assistant/agent.py:54` |
| 性能 | 20 万有效单元格上限，10 万行全量计算/差异 9.6s | `README.md:56`、`docs/PERFORMANCE.md` |

---

## 2. 对标参考

| 方向 | 开源参考 | 商业参考 | 可借鉴点 |
|---|---|---|---|
| NL → Excel 公式 | Grist 的 Formula Assistant、FormulaJS | Microsoft Copilot for Excel、Formula Bot、Numerous.ai、Rows.com | 公式生成 + 中文解释 + 逐单元格预览 |
| 可视化图表 | Apache ECharts / vChart、XlsxWriter 原生图表 | Julius AI、ChatGPT 高级数据分析 | 一句话出图 + 导出原生 Excel 图表 |
| 交互式透视 / 视图 | Grist、Baserow、NocoDB | Airtable、Rows.com | 拖拽分组聚合、透视视图 |
| 对话式数据分析 | PandasAI、smolagents、Open Interpreter | Julius、ChatGPT Code Interpreter | 分析过程可视化、逐步确认、可撤销 |
| 大文件 / 多表 | DuckDB、Polars、Gigasheet | Power Query / Power Pivot | SQL 关联、列式引擎、亿级行 |
| 本地/内网推理 | Ollama、vLLM、Xinference、SGLang、llama.cpp | 各家私有化部署 | 模型路由、Prompt caching、结构化输出 |
| 自动化 / 规则库 | n8n、Airtable Automations | Zapier | 批量多文件、定时/触发任务 |

---

## 3. 优化方向（按优先级）

### P0 · 补齐「对话式 Excel」核心三缺口

#### 方向 1：自然语言 → Excel 原生公式（NL2Formula）
- **差距**：用户仍需手写 36 个白名单公式；无「解释某格公式在算什么」。
- **目标**：「新增一列，按物料分组求累计金额占比」→ 生成 `SUMIFS(...)/SUM(...)` 原生公式并写回单元格，附中文解释；选中任意单元格可「用大白话解释这个公式」。
- **方案**：新增 MCP 工具 `formula_generate(selection, intent)` / `formula_explain(cell)`，让模型**只产出公式字符串 + 解释**（不执行代码），经 `workbook_model.py` 白名单校验 + 循环检测后落盘。公式是确定性文本，安全性高、内网友好。
- **参考**：Formula Bot、Numerous.ai、Grist Formula Assistant。
- **内网**：纯文本生成，模型只需做 NL→结构化输出，本地小模型可胜任。

#### 方向 2：可视化图表
- **差距**：完全无图表，含图表的 xlsx 导入即只读。
- **目标**：对话「把各物料库存画成柱状图」→ 客户端 ECharts/vChart 即时渲染预览 + 导出为 **XlsxWriter 原生图表**（line/bar/pie/scatter/area），双端一致。
- **方案**：前端加 `ChartPreview.vue`（读 `datacraft_preview` 结果渲染）；导出侧在 `workbook_excel.py:export_workbook` 增加 chart 段落。数据到图表走「列画像选轴」提示模型。
- **参考**：ECharts、XlsxWriter charts、Julius AI。
- **内网**：图表库随包内置，无 CDN。

#### 方向 3：透视表（Pivot）
- **差距**：Excel 原生透视表导入即只读；现有 `pivot` 操作只是 pandas 拉平成宽表。
- **目标**：两档——(a) 交互式透视视图（参考 Grist/Baserow，拖拽行/列/值/聚合）；(b) 对话生成**真·Excel 透视表**（openpyxl 支持 PivotTable），导出可被 Excel 识别。
- **方案**：视图档复用 Univer 现有排序/过滤插件 + 前端聚合；导出档在 `workbook_excel.py` 增加 pivot 段落。风险点：openpyxl 透视表读写能力有限，先做「生成」再做「保留回读」。
- **参考**：Grist、Baserow、Microsoft Excel PivotTable。

### P1 · 对话 / Agent 能力升级

#### 方向 4：数据画像注入（语义上下文）
- **差距**：Agent 靠 `datacraft_preview` 最多 200 行原文猜结构；内网模型 token 贵，原文浪费且易错。
- **目标**：注入「列画像」——每列 类型/基数/空值率/重复率/取值示例/数值分布/异常值，替代原文。这是**准确率提升性价比最高**的一步。
- **方案**：`data_toolkit/profiling.py` **已存在**，把它封装成 MCP 工具 `datacraft_profile`，并在 `mcp_server.py` 的 system prompt 中要求「先 profile 再操作」。前端可选展示数据质量卡片（缺失/重复/离群高亮）。
- **参考**：PandasAI、LlamaIndex 的列摘要。
- **内网**：画像比原文省 3–10× token，直接降低内网模型延迟与成本。

#### 方向 5：自有 Agent 循环 + 结构化输出
- **差距**：依赖 Qwen Code CLI 子进程，5 工具、20 轮上限，扩展受制于 CLI 行为。
- **目标**：自有轻量 agent 循环（规划 → 工具 → 校验 → 自愈），直接用 `assistant/mcp_server.py` 的 FastMCP 工具 + function-calling，输出用 JSON schema 强约束（`models.py` 的 `StrictModel` 已是 extra=forbid 的现成契约）。
- **方案**：抽 `assistant/agent.py` 为「规划器 + 执行器」两段：规划器产出 `OperationPlan` 后由确定性 `run_operation` 执行；失败时把 `issues` 回喂模型自愈一次。保留 Qwen Code 作为可选后端，新增直连 OpenAI 兼容端点的 function-calling 后端。
- **参考**：smolagents、LangGraph、PandasAI。
- **内网**：去掉对 CLI 的硬依赖，支持任意 OpenAI 兼容内网端点（vLLM/Ollama/Xinference）。

#### 方向 6：对话界面增强
- **差距**：非流式、工具调用过程不可见、不可撤销。
- **目标**：流式输出；对话里展示「执行了哪些步骤、每步行数变化、生成的差异」；支持「撤销上一步/回退到第 N 步」。
- **方案**：`api/api.py` 增加 SSE/流式通道；复用现有 `events` 表和 `Workbooks.apply` 的「候选 + 采用」模式做逐步确认。可撤销靠已有的 SQLite 版本链（`workbook_versions`）。
- **参考**：ChatGPT Code Interpreter、Julius AI 的步骤回放。

### P2 · 释放沉睡能力 + 内网模型矩阵

#### 方向 7：接线 `data_toolkit` 的沉睡能力
- **差距**：profiling / duckdb 数据库 / sql_runner / reporting / audit / validation / polars 引擎**未接线**（`assistant/tables.py` 只 import 4 个函数）。
- **目标**：
  - `datacraft_sql`：多表/大文件用 DuckDB SQL 关联（内网 ERP 导出场景，已有 `data_toolkit/sql/kingdee_bom.sql` 雏形）。
  - `datacraft_report`：自动生成数据质量报告（行数/缺失/重复/离群/对账差异汇总）。
  - `datacraft_audit`：数据血缘（每一步产出 ← 哪份输入 ← 哪个操作）。
  - 大文件走 polars 引擎（>50MB CSV/TSV 自动切换，`engine.py:choose_engine` 已实现）。
- **方案**：把这些封装成新的 MCP 工具并纳入 `agent.py:TOOLS` 白名单；UI 的「常用操作」下拉加「SQL 关联 / 数据报告 / 血缘」入口。
- **参考**：DuckDB、Gigasheet、Power Query。
- **内网**：全部本机计算，无外发。

#### 方向 8：本地 / 内网模型适配矩阵
- **差距**：仅 OpenAI 兼容端点；无本地推理、无多模型路由、无降级。
- **目标**：支持 Ollama / vLLM / Xinference / SGLang / llama.cpp / MindIE 等内网部署；「小模型做公式/分类/画像，大模型做规划」路由；主模型不可用时自动降级到本地小模型（保底可用）。
- **方案**：新增 `assistant/model_registry.py`，抽象 `list_models / complete / stream / function_call`；把现有 `agent.py:options()` 的端点拼装收敛到这里。开启 prompt caching（复用「列画像 + system prompt」稳定前缀）降延迟。
- **参考**：Ollama、vLLM、Xinference。
- **内网**：核心诉求——完全离线、可私有化、密钥走环境变量（已用 `EXCEL_ASSISTANT_API_KEY`）。

#### 方向 9：沙箱化代码执行（后期、可选）
- **差距**：任意 Python 已关闭（`README.md:52`，OS 隔离未完成）。
- **目标**：解锁「任意数据变换」——当 13 类操作 + SQL 覆盖不了时，让模型生成受限 Python 并执行。
- **方案（仅当内网安全评审通过后）**：Windows 受限令牌 / AppContainer / 作业对象限制内存与 CPU，禁网（`NO_PROXY=*` 已在用），只读挂载任务目录，白名单第三方库，输出强校验后才登记。**建议 P2 末 / P3 再评估，不作为短期目标。**
- **参考**：Julius、ChatGPT Code Interpreter、Open Interpreter。
- **风险**：内网环境下代码执行是最大攻击面，需 OS 隔离 + 审计双保险。

### P3 · 企业化 / 规模化

#### 方向 10：规则库 + 批量 / 定时自动化
- **现状**：已有「保存常用任务」（recipes），但单任务单文件槽位。
- **目标**：一批文件批量套用同一规则；定时/触发任务（每天 9 点对账）；规则市场（部门共享的「周报 / 对账 / BOM 汇总」模板）。
- **参考**：n8n、Airtable Automations、Zapier。
- **内网**：定时任务用本机/内网调度，无外网依赖。

#### 方向 11：内网协作 / 服务化（远期）
- **现状**：单机单实例（`README.md:57`）。
- **目标**：参考 Grist/NocoDB 自托管，演进为内网多用户协作的「表格 + AI + 数据库」，共享数据源、血缘、审计。
- **方案**：把 SQLite + 任务目录抽成可服务化存储，`api/api.py` 加鉴权与租户。**远期**，不在短期路线。

#### 方向 12：性能上限
- **现状**：20 万单元格、10 万行 9.6s。
- **目标**：DuckDB/polars 后端（已就绪）支撑百万行级；超出编辑器上限时走「流式分页 + 全量后台处理」（现有模式）。
- **落地（2026-09-19，见 `docs/PHASE_D.md`）**：assistant 主读取路径接上引擎——xlsx 无公式时单遍读（约 1.9x），大 CSV 走 DuckDB（百万行起反超，300 万行约 2.5x），安全快速路径 + 语义等价回退。**勘误**：实际只有 `duckdb` 已安装；`polars`/`pyarrow` 未装，`engine.py`/`io.py` 里的 polars 分支仅供独立 CLI toolkit，assistant 主路径未用。预览已由 `PreviewService` 流式分页覆盖。
- **参考**：DuckDB、Gigasheet。

---

## 4. 内网 / 离线专项（横切所有方向）

1. **完全离线**：所有运行时（Node/CLI/Python/WebView2/图表库/模型权重）随包或内网制品库分发，无 CDN、无外呼（现状已做到，新功能需维持）。
2. **模型私有化**：优先适配 OpenAI 兼容内网端点（vLLM/Ollama/Xinference），支持本地权重加载；`agent.py:54` 已硬性 `NO_PROXY=*`。
3. **token 经济**：数据画像替代原文、prompt caching、小模型分流——内网模型慢且贵，这是硬约束。
4. **脱敏与审计**：`data_toolkit/audit.py` 血缘 + `assistant/diagnostics` 脱敏报告，任何 AI 产出先「候选」后「人工采用」，不外发文件内容。
5. **降级可用**：无模型时 13 类确定性操作 + 公式 + 图表仍可用（现有「三层价值」已保证，新功能同样要求无模型兜底）。
6. **安全边界**：代码执行（方向 9）必须 OS 隔离 + 审计通过才开放；其余方向坚持「模型只产出文本/结构化参数，执行走确定性内核」。

---

## 5. 分阶段路线图

| 阶段 | 内容 | 交付物 |
|---|---|---|
| **Phase A（近期）** | 方向 1 公式生成/解释 + 方向 4 数据画像 + 方向 7 接线 duckdb/sql/report | 对话能「生成公式、解释公式、SQL 关联、出质量报告」，准确率随画像显著提升 |
| **Phase B（中期）** | 方向 2 图表 + 方向 6 流式/撤销 + 方向 8 模型矩阵 | 一句话出图导出原生图表；对话流式且可逐步确认/撤销；支持本地模型 |
| **Phase C（中长期）** | 方向 3 透视 + 方向 5 自有 agent 循环 + 方向 10 批量/定时 | 透视视图与真透视表；脱离 CLI 的自有 Agent；批量自动化 |
| **Phase D（远期）** | 方向 9 沙箱执行 + 方向 11 协作服务化 + 方向 12 性能 | 视内网安全评审与企业需求推进 |

> 建议第一步从 **Phase A** 起步：方向 4（画像）是准确率杠杆，方向 7（接线沉睡能力）是零成本挖潜，方向 1（公式）直接命中「不写公式」的产品承诺。

---

## 6. 风险与边界

- **openpyxl/XlsxWriter 对图表、透视表、条件格式的保真度有限**：方向 2/3 需「先生成、后保留回读」分步走，避免声称「无损」。
- **内网模型效果未验收**（`README.md:51`）：所有依赖模型的方向都需在客户模型上实测，画像/公式这类「结构化输出」任务比开放式规划更容易达标。
- **代码执行（方向 9）是安全最大变量**：不解决 Windows OS 隔离就不开放，保持现状「模型不执行代码」。
- **单实例单任务**（现状边界）会限制协作/自动化方向的体验，Phase C 前需评估解耦。
