# Phase C 实施设计：透视表（交互式视图 + 真·Excel 透视表）

> 本文是 `docs/OPTIMIZATION.md` 方向 3 的落地设计。目标：用户不写公式/VBA/Python，即可**交互式透视**任意数据源，并能**生成可被 Excel 识别的原生透视表**。全程内网离线、确定性执行。
>
> 核心原则（沿用现状）：**模型只产出文本或结构化参数，执行走确定性内核，结果先「候选」后「人工采用」，不覆盖源文件**。本阶段不引入任何代码执行。

---

## 0. 现状与差距

| 项 | 现状 | 位置 |
|---|---|---|
| `pivot` 操作 | pandas `pivot_table` 拉平成**宽表矩阵**（长表→矩阵），单列名、单值、单聚合 | `assistant/tables.py:215` |
| 原生透视表 | **导入即只读**：preflight 拦截 `xl/pivotTables/` | `assistant/workbook_excel.py:30` |
| 导出引擎 | XlsxWriter（**不支持透视表**）；openpyxl 3.1.5（`openpyxl.pivot.table` 仅有读侧 `TableDefinition`，**无写侧 API**） | `assistant/workbook_excel.py:318` |
| 图表先例 | `run_chart` 写原生图表 + 内联 `chart` 字典 → `ChartPreview.vue` 渲染 | `assistant/tables.py:349`、`gui/src/ChartPreview.vue` |

**技术结论**：openpyxl 与 XlsxWriter 都不能生成原生透视表，故「真·Excel 透视表」需**自研最小化 OOXML 透视表写入器**（生成型，非回读保真型）。

---

## 1. 目标（两档）

- **档 a · 交互式透视视图**（主交付，零模型依赖）：选定数据源后，多选「行/列/值」字段 + 聚合方式，**实时预览**聚合矩阵；「应用」走现有确定性 `pivot` 落盘为候选输出。
- **档 b · 真·Excel 透视表**（生成型）：由数据源 + 透视规格，生成含**原生透视表**的 xlsx（`xl/pivotTables/` + 缓存部件），导出可被 Excel 识别并继续交互。

---

## 2. 档 a：交互式透视视图

### 2.1 后端：只读实时预览 RPC
新增 `pivot.preview`（`api/api.py`）：
```python
@api_method('pivot.preview')
def pivot_preview(task_id, selection, rows, columns, values, aggregate='sum'):
    # read(store, task, selection) → pandas pivot_table → 紧凑 records
    # 返回 {"labels": {"rows": [...], "columns": [...]}, "rows": [...], "total": n}
```
- 只读、不落盘、不写输出；聚合方式 `{sum,count,min,max,mean}`。
- **容量钳制**：结果单元格 > 5000 时报错提示「缩小行列或聚合范围」，避免前端大载荷。
- 复用 `tables.read` + 现有 `pivot` 分支的 `pivot_table` 逻辑（提取为公共函数 `aggregate_pivot`）。

### 2.2 后端：`pivot` 操作支持多值
扩展 `assistant/tables.py` `pivot` 分支与 `Operation` 语义：`params` 兼容旧 `{keys,column,value,aggregate}`，新增 `values:[str]`（多值，各按 `aggregate` 聚合）。旧 `value` 仍可用。

### 2.3 前端：`PivotBuilder.vue` + App.vue 接线
- 新组件 `gui/src/PivotBuilder.vue`：字段选择（行 `rows` 多选、列 `column` 单/空、值 `values` 多选）+ 聚合下拉 + **实时预览表**（防抖调 `pivot.preview`）。
- 复用现有 `App.vue` 的 `pivot` 表单入口，替换为 PivotBuilder（`keys`→rows、`pivotColumn`→column、`pivotValue`→values、新增 aggregate 下拉），「开始处理」走现有 `tasks.execute` 的 `pivot` step。

---

## 3. 档 b：真·Excel 透视表（生成型）

### 3.1 数据模型：新 `Operation.kind = "pivot_table"`
- `assistant/models.py`：`Literal` 增加 `'pivot_table'`；`input_count` 走单文件输入（与 `chart`/`report` 一致，用文件输入、禁止工作簿输入）。
- `params` 契约：
  ```json
  {"rows": ["物料"], "columns": ["地区"], "values": [{"field": "数量", "aggregate": "sum"}], "name": "透视表"}
  ```
  首版约束：`rows` ≥1、`columns` ≤1、`values` =1（多值留作后续）。
- `STEP_LABELS` 增加 `pivot_table: "生成透视表"`。

### 3.2 原生透视表写入器：`assistant/pivot_excel.py`（新）
- `build_pivot_xlsx(frame, spec, target)`：数据写入「数据」工作表（XlsxWriter，复用 `publish` 的安全写入：`strings_to_formulas=False`、临时文件+校验+原子改名），随后**向 zip 注入原生透视表部件**：
  - `xl/pivotTables/pivotTable1.xml`（`pivotTableDefinition`：`location`、`pivotFields`、`rowFields`/`colFields`/`dataFields`，引用 cache）
  - `xl/pivotCache/pivotCacheDefinition1.xml` + `pivotCacheRecords1.xml`（含去重记录，Excel 打开即可用、不弹「刷新」）
  - 新工作表「透视表」（`xl/worksheets/sheet2.xml`，引用 pivotTable 部件）
  - 更新 `[Content_Types].xml`、`xl/workbook.xml`、`xl/_rels/workbook.xml.rels`、各 `_rels`
- 关键不变量：字段名转英文标识符或保留原样但 XML 转义；`pivotCacheRecords` 数值/文本类型正确；**只生成、不回读保真**。

### 3.3 执行与接线
- `assistant/tables.py`：新增 `run_pivot_table`（`read` → `build_pivot_xlsx` → 登记候选输出 + `publish` 同款 info），`run_operation` 增加 `pivot_table` 分支。
- `assistant/mcp_server.py`：新增 `datacraft_pivot_table` 工具（镜像 `datacraft_chart`），纳入 `planner.py` 的观测/执行工具 schema 与 system 提示。
- 前端：`App.vue` `operations` 字典 + `ResultPanel.vue` 增加「透视表」入口与 `pivot` 内联预览（复用 FilePreview 展示「数据」sheet；原生透视表用「用 Excel 打开」查看）。

---

## 4. 内网 / 安全约束

1. **无代码执行**：透视聚合走 pandas `pivot_table` 确定性内核；原生透视表由自研 OOXML 写入器生成，模型文本不当指令。
2. **无外发**：全部本机计算与落盘，`NO_PROXY=*`、`httpx trust_env=False` 不变。
3. **候选不落地为成品**：`pivot`/`pivot_table` 结果走候选输出，不覆盖源文件；原生透视表为一次性输出，经「用 Excel 打开」核对。
4. **降级可用**：档 a 零模型依赖；档 b 的 `pivot_table` 是确定性 step，无模型也可由「常用操作」表单触发。
5. **回读边界（如实声明）**：生成的原生透视表若重新导入编辑器，仍按现状进入只读（`xl/pivotTables/` preflight 不变）；「透视表保留回读」不在本阶段。

---

## 5. 涉及文件

- 改：`assistant/models.py`（+`pivot_table`）、`assistant/tables.py`（`pivot` 多值 + `run_pivot_table` + `aggregate_pivot` 抽取）、`assistant/mcp_server.py`（+`datacraft_pivot_table`）、`assistant/planner.py`（工具 schema/提示）、`api/api.py`（+`pivot.preview`）、`gui/src/App.vue`、`gui/src/ResultPanel.vue`、`gui/src/rpc.ts`（+类型）
- 新增：`assistant/pivot_excel.py`、`gui/src/PivotBuilder.vue`、`tests/test_pivot.py`
- 复用（不改）：`assistant/tables.py` 的 `read/publish`、`data_toolkit` 无、`assistant/workbook_excel.py` 的 XlsxWriter 安全写入模式

---

## 6. 验证方式

1. **单元测试**（`tests/test_pivot.py`）：
   - `aggregate_pivot`：多值/单值/多行/空列聚合正确；非法聚合/字段被拒；容量钳制生效。
   - `build_pivot_xlsx`：产物可被 openpyxl 只读打开；zip 内含 `xl/pivotTables/pivotTable1.xml`、`pivotCacheDefinition1.xml`、`pivotCacheRecords1.xml`；`[Content_Types].xml` 含透视内容类型；`pivotTableDefinition` 能被 openpyxl 读侧 `TableDefinition` 解析（round-trip 结构校验）。
   - `pivot_table` 操作：`run_operation` 产出候选输出、`STEP_LABELS`/`emit_step` 正确、单文件输入校验（多输入/工作簿输入被拒）。
2. **RPC 冒烟**：`pivot.preview` 走真实 CSV 返回矩阵；`pivot_table` 走真实 CSV 产出含透视表的 xlsx。
3. **全量回归**：`python -m unittest discover -s tests -v` 无回归；`cd gui && npx vue-tsc --noEmit` 通过。
4. **Excel 实机验收（后补）**：生成的原生透视表在 Excel 2016+ 打开无修复提示、可改字段（本阶段测试环境无实机 Excel，与图表/模板同款「需 Excel 实机验收」提示）。
