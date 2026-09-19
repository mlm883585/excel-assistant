# 方向 11 · 内网协作 / 服务化（远期设计）

更新：2026-09-19。**触发条件：企业有明确多用户/协作需求，且通过内网安全评审后启动。** 当前单机单任务已覆盖个人场景，本方向不进入短期实现。

## 现状（单实例，已勘察）

| 维度 | 现状 |
| --- | --- |
| 形态 | Windows 桌面 pywebview + ppx_py RPC（`main.py` 注册 `api/api.py`），单进程单用户 |
| 存储 | `assistant/store.py::Store`：SQLite WAL `tasks.sqlite` + `%LOCALAPPDATA%/ExcelAssistant/tasks/<id>/` 文件目录；`import_file` 复制源文件进任务目录 |
| 执行 | `assistant/jobs.py` 全局单任务 spawn 子进程 + `SchedulerService` 应用内定时 |
| 边界 | 无鉴权、无租户、无跨用户共享；血缘/审计仅单用户可见 |

依赖已具备（`requirements.lock.txt` 内已有 `starlette`/`uvicorn`/`sse-starlette`/`PyJWT`/`python-multipart`，来自 mcp/ppx 传递依赖，可为服务层复用）。

## 目标

参考 Grist/NocoDB 自托管，演进为内网多用户协作的「表格 + AI + 数据库」：共享数据源、血缘、审计。

## 分阶段方案（可逆，每步不破坏现有单机形态）

### 阶段一：存储可服务化（零产品行为变化）
- 把 `Store` 抽为接口（`TaskStore` / `EventStore` / `RecipeStore` / `ScheduleStore`），当前 SQLite 实现作为一等实现保留；任务目录的文件读写全部收口到 `Store`。
- 收益：为替换共享后端铺路，桌面单机行为不变。

### 阶段二：传输无关服务层 + HTTP 入口
- 现有 `api/api.py` 是 `@api_method`（ppx_py RPC）薄封装业务；把业务方法抽成与传输无关的 service 层，新增 FastAPI/uvicorn HTTP 入口复用同一 service。
- 桌面壳保留 WebView2，另开放浏览器访问；`store`/`jobs` 单例改为按请求作用域注入。

### 阶段三：鉴权与租户隔离
- 内网单服务实例；`PyJWT` 签发令牌；`user` / `tenant` 两个维度隔离（SQLite 加 `tenant_id` 或每租户分库，视规模定）。
- 源文件、任务、输出、规则、定时、预览缓存均按租户隔离；审计日志复用 `data_toolkit/audit.py` 血缘 + `assistant/diagnostics` 脱敏，并加租户维度。

### 阶段四：共享数据源与协作
- 数据源注册表（共享表/连接/规则），血缘跨用户可见；「候选 → 人工采纳」与审计贯穿，任何 AI 产出不外发文件内容。

## 安全不变式（延续，不因服务化放宽）

- 模型只产出文本/结构化参数，执行走确定性内核；服务化不引入任意代码执行（方向 9 仍关闭）。
- 多用户下脱敏更严格：AI 侧不落明文文件内容，`httpx` 维持 `trust_env=False, follow_redirects=False`、`NO_PROXY=*`。
- 完全离线：自托管在客户内网，无外呼；密钥只走环境变量，配置不落库。

## 交付物（激活后）

设计评审记录、鉴权/租户方案、服务层接口契约、SQLite→共享后端迁移脚本、多用户离线验收清单（在 `OFFLINE_ACCEPTANCE.md` 基础上扩租户/审计项）。
