# Phase D · 方向 12：性能（向百万行级推进）

更新：2026-09-19。

## 目标与现状

把大文件「读取 → 处理 → 导出」链路向百万行级推进，复用已就绪的引擎，同时**绝不牺牲正确性**（结果仍是「候选 → 人工采纳」，源文件只读不变式不变）。

勘察结论（本次实测）：

| 事实 | 结论 |
| --- | --- |
| `duckdb==1.5.5` 已安装；`polars`/`pyarrow` 未安装 | 「DuckDB/polars 后端已就绪」实为 **DuckDB 就绪**；`data_toolkit/engine.py`、`io.py` 里的 polars 分支是给独立 CLI toolkit 的，assistant 主路径从未调用 |
| assistant 数据主路径 `assistant/tables.py::read` 纯 pandas + openpyxl（xlsx 双遍公式/值）+ calamine（xls） | 大文件读取是纯 pandas，未用任何加速 |
| 预览已流式化（`assistant/preview.py::PreviewService` 后台索引 SQLite 分页） | 预览非本次重点 |
| 基线（`docs/PERFORMANCE.md`）：3×100k 行×30 列 xlsx，读取 104.96s / 合并计算 0.035s / 导出 78.97s / 全流程 204s | 瓶颈在 **xlsx 读取（openpyxl 双遍）** 与 **导出（xlsxwriter 速度上限）** |

## 原则：安全快速路径

每一项优化都遵循「满足条件走快速路径，不满足回退现有语义等价路径」：
- 快速路径只处理**可证明等价**的常见形态；
- 任何不确定（异常编码、公式、空行、参差不齐行）→ 回退现有 pandas/openpyxl 路径；
- 快速路径不改变任何输出语义（列名、取值、`__source_*` 来源列、公式校验报错、编号格式补零）。

## 改动

### 1. XLSX 读取：无公式时单遍读（`assistant/tables.py`）

现有 `read()` 对 `.xlsx` 恒做 **双遍** openpyxl（`data_only=False` 拿公式 + `data_only=True` 拿缓存值），逐格比对。公式校验是安全需求（确保客户公式已重算），但**纯数据导出类工作簿没有公式**，双遍是纯开销。

- 新增 `_xlsx_has_formula(path)`：读 `xl/worksheets/*.xml`，用 `<(?:[A-Za-z_][\w.-]*:)?f[ >/]` 探测公式元素（含命名空间前缀形式；实测值单元格 `<v>`、列定义 `<col>`、`<filters>` 均不误报；字符串文本被 XML 转义为 `&lt;` 不会误命中）。
- 无公式时**单遍** `load_workbook(read_only=True, data_only=True)` 读值，仍保留编号格式补零（实测 `data_only` read_only 下 `cell.number_format` 可用）。
- 有公式（或 zip/解码异常）→ 回退现有双遍路径，语义完全不变。

收益：纯数据 xlsx 读取约 2 倍；安全性由「无 `<f>` 才快路径」保证。实测（100k 行×3 列，`scripts/benchmark_performance.py`）：单遍 6.7s vs 双遍 12.6s（约 1.9x）。

### 2. CSV 读取：大文件 DuckDB 快速路径（`assistant/tables.py`）

现有 `.csv` 用 `pd.read_csv(dtype=str, skip_blank_lines=False)` 全量读。新增 `_read_csv_fast(path)`：

- 阈值 `CSV_FAST_MIN_BYTES = 10 * 1024 * 1024`，小文件直接走 pandas（避免 DuckDB 启动与二次读的开销倒挂）。
- 流式校验编码为 utf-8-sig（`codecs.getincrementaldecoder`，失败即回退 pandas 走 gb18030），同时统计物理行数。
- DuckDB `read_csv(header=false, all_varchar=true, delim=',', ignore_errors=false)` 读取（`header=false` 令每行成一列数可变的字符串行，任意 `header_row` 都能在共享切片代码里复用）。
- **等价校验**：`len(frame) == 物理行数`。DuckDB 会丢弃空行（实测），行数不相等即存在空行 → 回退 pandas，保证 `__source_row` 物理行号精确；参差不齐行 DuckDB 直接报错（实测）→ 回退。
- 空字段补 `''`（`frame.where(pd.notna, "")`），对齐 `keep_default_na=False` 语义。

收益：时间在百万行级起反超 pandas（实测：1M 行 0.36s vs 0.47s；300 万行 0.88s vs 2.19s，约 2.5x，pandas `dtype=str` 随规模超线性劣化）；峰值内存略高（`fetchdf` 物化对象列，约 1.4x），属可接受的瞬时成本。10MB 阈值避免小文件惩罚（100k 行时 DuckDB 反慢 0.11s vs 0.04s，故小于阈值直接走 pandas）。

### 3. 基准与测试

- `scripts/benchmark_performance.py`：合成 100k 行（CSV + 无公式 xlsx + 有公式 xlsx），对比读取耗时与结果一致性。
- `tests/test_performance.py`：小规模但覆盖——CSV 快速/回退取值一致、空行回退、gb18030 回退、小文件回退、`__source_row` 精确；xlsx 无公式单遍与双遍结果一致、有公式仍走双遍并触发公式校验报错。

## 二期（本期不做，记录理由）

- **聚合/关联走 DuckDB**：`group`/`pivot_table` 已是 pandas C 内核；`join`/`append` 百万行内存是真实瓶颈，但转 DuckDB 需对齐 `to_numeric(errors="raise")`、NaN/空串、`dropna=False`/`sort=False` 等类型语义，风险高，留待独立一期。
- **导出**：`publish()` 已用 xlsxwriter 流式写，时间受 xlsx 压缩/写盘上限约束；进一步收益在「超大结果改出 CSV/parquet 或 `constant_memory`」，属产品行为变更，另议。

## 关键文件

- 改：`assistant/tables.py`（`_read_csv_fast`、`_xlsx_has_formula`、`read()` 分支）、`docs/PHASE_D.md`
- 新增：`tests/test_performance.py`、`scripts/benchmark_performance.py`
- 复用（不改）：`assistant/preview.py` 流式预览、`data_toolkit/sql_runner.py` DuckDB 只读 SQL、`run_operation` 确定性内核

## 验证

1. `tests/test_performance.py` 全绿（等价 + 回退覆盖）。
2. 全量回归 `.venv\Scripts\python.exe -m unittest discover -s tests -v` 无回归。
3. `scripts/benchmark_performance.py` 输出前后耗时对比，确认快速路径未改变结果（行数/列名/来源行/抽样值一致）。
