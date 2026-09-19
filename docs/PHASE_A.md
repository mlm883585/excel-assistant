# Phase A 实施设计：公式生成/解释 · 数据画像 · 接线沉睡能力

> 本文是 `docs/OPTIMIZATION.md` 中 Phase A 的落地设计。目标：用户**对话即可**生成/解释 Excel 公式、获得数据画像、做 SQL 关联与数据报告——全程不写公式/代码，内网离线可用。
>
> 核心原则（沿用现状）：**模型只产出文本或结构化参数，执行走确定性内核，结果先「候选」后「人工采用」**。本阶段不引入任何代码执行。

---

## 0. 新增 MCP 工具总览

| 工具 | 类型 | 复用 | 校验/安全 | 归属 |
|---|---|---|---|---|
| `datacraft_profile` | 只读 | `tables.read` + `profiling.profile_dataframe` | 列样本截断 | 方向 4 |
| `datacraft_sql` | 产出候选 | `tables.read` + `sql_runner.run_query` | `validate_readonly_sql`（只读单查询，禁外部访问） | 方向 7 |
| `datacraft_report` | 产出候选 | `reporting.write_report` + `profile_dataframe` | 结果写 outputs，不覆盖 | 方向 7 |
| `datacraft_audit` | 只读 | `store` 的 `plan` + outputs | 只读摘要 | 方向 7 |
| `datacraft_formula_generate` | 只读（起草） | `workbook_model.formula_issue` | 白名单校验后才返回 | 方向 1 |
| `datacraft_formula_explain` | 只读 | 读取快照单元格 `formula` | 只读 | 方向 1 |

公式**写回**不新增工具，走现有 `datacraft_execute(edit_workbook)`，新增一个 `set_formula` 编辑动词（见 §2）。

所有新工具都需加入 `assistant/agent.py:9 TOOLS` 白名单；`agent.py:36` 的 `mcp__datacraft__` 前缀匹配已通用，无需改权限回调。

---

## 1. 方向 4：数据画像（datacraft_profile）

### 现状与目标
- 现状：Agent 靠 `datacraft_preview` 最多 200 行原文猜结构，token 浪费、易误判列类型/取值。
- 目标：注入「列画像」——类型/空值率/唯一数/取值示例/数值范围，替代原文作为 Agent 上下文，同时支持前端「数据质量卡片」。

### 后端改动
1. **`data_toolkit/profiling.py` 扩展**：新增 `profile_columns(frame, sample_limit=5) -> list[dict]`，在现有 `profile_dataframe`（字段/类型/记录数/空值/唯一/重复/最小/最大）基础上，为每列补充**非空取值示例**（按频次取 top N，串/数值皆可），并压成紧凑字典，避免把整列塞进上下文。
2. **`assistant/mcp_server.py` 新增工具**：
   ```python
   @server.tool()
   def datacraft_profile(selection: InputSelection, sample_limit: int = 5) -> dict:
       frame = read(store, task, InputSelection.model_validate(selection))
       return {"row_count": len(frame), "column_count": len(frame.columns),
               "columns": profile_columns(frame, sample_limit)}
   ```
   返回为紧凑 JSON（示例见下），显式排除 `__source_*` 系统列。
3. **`assistant/agent.py` 系统提示注入**：在 `append_system_prompt` 追加「处理前先 `datacraft_profile` 了解字段；不要仅凭预览猜类型；字段歧义用 `ask_user_question`」。这是准确率提升的关键一步。

### 前端（可选，第二优先级）
`ResultPanel` / 文件面板加「数据质量」入口：调用 `datacraft_profile` 结果渲染成表格（字段/空值率/唯一数/示例），缺失率>阈值高亮。首版可只做只读展示，不改写数据。

### 涉及文件
- 改：`data_toolkit/profiling.py`（+`profile_columns`）、`assistant/mcp_server.py`、`assistant/agent.py`
- 前端（可选）：`gui/src/App.vue` + 新 `DataProfile.vue`

---

## 2. 方向 1：NL 公式（formula_generate / formula_explain / set_formula）

### 现状与目标
- 现状：36 个白名单函数需手写；无公式解释；`edit_workbook` 只允许 `set_values/set_style/add_sheet/rename_sheet`。
- 目标：选单元格→「算金额=数量×单价并解释」→ 生成公式（先校验）→ 写入候选 → 人工采用 → 编辑器重算 → 导出。

### 数据模型：新增 `set_formula` 编辑动词
`assistant/workbook_operations.py:edit_workbook` 增加一个分支（复用 `cell()` 之外的公式单元格构造）：
```python
elif kind == 'set_formula' and not set(edit) - {'kind','sheet_id','range','formulas'}:
    area = edit['range']; validate_range(area)
    # formulas: 与选区等尺寸的矩阵，每项为 '' 或以 '=' 开头
    for r, c 遍历选区:
        f = edit['formulas'][...]
        if f:
            issue = formula_issue(f)          # 白名单 + 数组/外部引用拦截
            if issue: raise ValueError(issue)
            target['cells'][key] = {'formula': f, 'value': None, 'result_state': 'pending'}
        else:
            target['cells'].pop(key, None)     # 清空
```
要点：
- 复用 `workbook_model.formula_issue`（`workbook_model.py:47`）做白名单校验，**不信任模型文本**。
- 写为 `result_state='pending'`、`value=None`；`edit_workbook` 末尾已 `invalidate_formulas()`（`workbook_operations.py:85`），与现有候选→采用→Univer 重算链路完全兼容。
- 范围校验沿用 `run_workbook_operation` 的「不扩大用户选区」逻辑（`workbook_operations.py:99-106`），公式编辑同样受选区约束。

### 新工具（只读起草，提升可靠性）
1. `datacraft_formula_generate(selection, request)`：模型先描述意图，此工具用 `formula_issue` **预校验**并返回
   ```json
   {"candidates":[{"range":{...},"formula":"=C2*D2","ok":true,"issue":null}],
    "explanation":"金额列 = 数量列 × 单价列，结果保留两位小数"}
   ```
   失败时返回 `ok:false` + 原因，让 Agent 就地修正，避免整轮 candidate 往返。
2. `datacraft_formula_explain(selection)`：读快照中该单元格 `formula`，返回公式字符串 + 中文逐步解释（模型生成解释文本，公式来自快照，不来自模型）。

### 对话流
1. 用户在编辑器选中区域，说「新增金额列 = 数量×单价，并解释」
2. Agent → `formula_generate`（校验）→ `datacraft_execute(edit_workbook, set_formula)` → 产出 `workbook_candidate`
3. 用户走现有「结果与核对」查看差异 → 采用 → Univer 重算 → 导出（`Workbooks.apply` / `outputs.export` 已就绪）

### 涉及文件
- 改：`assistant/workbook_operations.py`（+`set_formula`）、`assistant/mcp_server.py`（+2 工具）、`assistant/agent.py`（白名单 + 提示词）
- 复用：`assistant/workbook_model.py:47 formula_issue`、`gui/src/workbook/formulaValidation.ts`（重算与 #CYCLE 标记）
- 前端无需新组件（现有编辑器 + 对话 + 候选核对已覆盖），仅 `ask()` 的 scope 提示已在 `App.vue:124` 注入选区。

---

## 3. 方向 7：接线沉睡能力（SQL / 报告 / 血缘）

### 3.1 datacraft_sql（DuckDB 只读关联）
- 复用 `data_toolkit/sql_runner.py:176 run_query(tables, query)`：内存 DuckDB、`validate_readonly_sql`（只允许单条 SELECT/WITH、禁外部文件读取、禁写），**安全内核已存在**。
- 新工具：
  ```python
  @server.tool()
  def datacraft_sql(query: str, tables: dict[str, InputSelection]) -> dict:
      frames = {alias: read(store, task, InputSelection.model_validate(sel)) for alias, sel in tables.items()}
      result = run_query(frames, query)   # 内部校验只读 SQL
      return publish(store, task, result, {}, {"input_tables": list(frames), "output_rows": len(result)}, [])
  ```
  复用 `tables.publish`（`tables.py:225`）把结果登记为候选输出（写 outputs、返回 info、记 issues/timings）。多表/大文件关联、ERP 导出 SQL 场景命中。
- 表别名→选区映射由模型从 `datacraft_files` + 用户描述构造；列名来自 `datacraft_profile`。

### 3.2 datacraft_report（数据质量报告）
- 复用 `data_toolkit/reporting.py:21 write_report(summary, field_profile, issues, extras)`：输出「汇总/字段概况/问题明细」多 sheet xlsx。
- 新工具：`read()` → `profile_dataframe()` → 组装 summary（行数/列数/空值数/重复行数）→ 写到 `store.directory(task)/outputs/<id>.xlsx` → 用 `publish` 同款 info 登记。
- 注意 `write_report` 会拒绝覆盖已存在文件（`reporting.py:31`），与项目「已有文件不覆盖」一致。

### 3.3 datacraft_audit（数据血缘，只读）
- 任务记录已具备血缘要素：`record["plan"]["steps"]`（`mcp_server.py:63-66` 追加的操作顺序）+ outputs 列表 + 结果里内嵌的 `__source_file/__source_sheet/__source_row` 来源列（`tables.py:16 SOURCE`）。
- 新工具：汇总「每一步 kind/输入/输出 id → 产出文件」的链路摘要，返回给用户/前端「血缘」视图；**无需新增存储**。

### 3.4 UI 接线
- `gui/src/App.vue:51 operations` 字典新增：
  - `sql` → 「SQL 关联」（多表：复用 `twoFiles` 之外的「多选输入」或直接用对话模式描述）
  - `report` → 「数据质量报告」（单输入）
- 首版可先只走**对话模式**（`mode==='agent'`）暴露 SQL/报告，避免复杂表单；「常用操作」下拉按需后续补充表单。

### 涉及文件
- 改：`assistant/mcp_server.py`（+3 工具）、`assistant/agent.py`（白名单）、`gui/src/App.vue`（可选 operations）
- 复用：`data_toolkit/sql_runner.py`、`data_toolkit/reporting.py`、`data_toolkit/profiling.py`、`assistant/tables.py:publish/read`

---

## 4. 内网 / 安全约束（贯穿 Phase A）

1. **无代码执行**：公式/SQL 都经确定性内核校验（`formula_issue` 白名单、`validate_readonly_sql` 只读单查询 + 禁外部函数），模型文本不当指令。
2. **无外发**：所有计算本机（DuckDB 内存、openpyxl/XlsxWriter 落盘），`NO_PROXY=*` 维持（`agent.py:54`）。
3. **token 经济**：`datacraft_profile` 以列画像替代原文，`datacraft_formula_generate` 预校验避免无效候选轮次——都是针对内网模型慢/贵的降本。
4. **降级可用**：无模型时，画像/报告/SQL 关联仍可通过「常用操作」表单或报告入口手动触发；公式仍需对话，但白名单校验与编辑器重算不依赖模型。
5. **候选不落地为成品**：SQL/报告产出走 `publish` 登记为 `validated` 输出但**不覆盖源文件**；公式写入走 `workbook_candidate`，人工采用后才可导出（现状不变式）。

---

## 5. 验证方式

1. **单元测试**（`tests/`，`unittest discover -s tests -v`）：
   - `set_formula`：合法公式通过、越白名单函数/数组/外部引用被拒、选区尺寸不符被拒、不扩大选区被拒。
   - `profile_columns`：串/数值/日期列样本、空列、全空值列边界。
   - `datacraft_sql`：多表 JOIN 正确、只读校验拦截 `DELETE/UPDATE/read_csv_auto` 等。
2. **MCP 工具冒烟**：`assistant/mcp_server.py` 的 `datacraft_profile/sql/report/audit/formula_generate` 各跑一条真实 xlsx。
3. **UI smoke**（`scripts/*.cjs` Playwright harness，可仿 `workbook_review_ui_smoke.cjs`）：对话「新增金额列=数量×单价」→ 候选出现 → 采用 → 编辑器显示重算结果 → 导出。
4. **端到端（`REQUIRE_QWEN_CLI=1` 时）**：真实模型走一遍「画像→SQL 关联→报告→公式」全流程，核对输出行数与 `issues`。

---

## 6. 任务拆解（建议顺序）

1. `profile_columns` + `datacraft_profile`（方向 4，最小改动、立竿见影）
2. `datacraft_sql`（复用 `run_query`/`publish`，解锁多表关联）
3. `set_formula` 编辑动词 + `formula_generate`/`formula_explain`（方向 1，命中「不写公式」）
4. `datacraft_report` + `datacraft_audit`（方向 7 收尾）
5. 前端接线 + 冒烟/端到端测试
