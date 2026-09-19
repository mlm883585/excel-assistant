# 内网离线交付：依赖自包含与重建

本文说明如何让「源码 + 离线物料」在内网机器上**零网络**重建出可交付的便携包，以及未来新增依赖时如何保持离线物料同步。

## 结论速览

- **运行时已完全离线**：便携包 `build/ExcelAssistant/` 内嵌 CPython 3.13 + 冻结依赖、随包 Node.exe v24.13.0、随包 Qwen Code CLI 0.23.3、随包 WebView2 离线安装器、前端已编译进 `web`。运行时唯一联网点是内网模型端点 + 内网更新服务，均默认关闭。
- **差距只在「构建/重建」**：59 个 PyPI wheel、283 个 npm 包、node.exe、WebView2 安装器此前未入库。本文的离线物料补齐这一点。
- **二进制不入 git**：`offline/`（wheelhouse + npm 缓存 + node.exe）与 `runtime/WebView2StandaloneX64.exe` 均 gitignored，由脚本在有网机器上生成、打包成单个 `offline-build-kit.zip` 搬进内网。

## 离线物料布局

```
offline/
  wheels/          # pip 全量 wheel（win_amd64 / py3.13）
  npm/             # npm 离线缓存（_cacache，覆盖 gui + 根两个项目）
  node/            # node.exe v24.13.0（nodejs.org 官方 zip 解出）
  manifest.json    # 生成时的 requirements.lock.txt + requirements-optional.txt + 两个 package-lock.json 的 SHA-256
runtime/WebView2StandaloneX64.exe   # 由 scripts/fetch_webview2.ps1 下载并 Authenticode 验签
```

## 脚本清单

| 脚本 | 作用 | 何时运行 |
| --- | --- | --- |
| `scripts/fetch_wheels.py` | 下载全量 Python wheel（`requirements.lock.txt` + `requirements-optional.txt` + 本地 qwen-code-sdk 打成 wheel）到 `offline/wheels` | 有网机器 |
| `scripts/fetch_npm_cache.ps1` | 用同一缓存跑两遍 `npm ci`，把 npm 包全量缓存到 `offline/npm` | 有网机器 |
| `scripts/fetch_node.ps1` | 下载 Node v24.13.0 解出 `offline/node/node.exe` | 有网机器 |
| `scripts/fetch_webview2.ps1` | 下载并验签 WebView2 离线安装器到 `runtime/` | 有网机器 |
| `scripts/refresh_offline.py` | **单一入口**：串联上面全部，并写 `offline/manifest.json` | 有网机器，依赖变化后 |
| `scripts/check_offline.py` | 漂移校验：锁文件变了但离线物料没刷新则退出码 1 | 构建前 / CI |
| `scripts/setup_venv_offline.py` | 零网络建 `.venv` 并从 wheelhouse 装齐依赖 | 内网机器 |
| `scripts/package_offline_kit.py` | 打包 `offline/` + WebView2 + 源码为 `build/offline-build-kit.zip` | 有网机器，交付前 |

## 有网机器：生成 / 刷新离线物料

```powershell
python scripts/refresh_offline.py     # 生成/更新 offline/ 与 manifest.json
python scripts/check_offline.py       # 校验通过（退出码 0）
python scripts/package_offline_kit.py # 产出 build/offline-build-kit.zip
```

`refresh_offline.py` 幂等：已存在且版本正确的 node.exe / WebView2 会跳过。

## 内网机器：零网络重建

```powershell
# 1. 解压 offline-build-kit.zip，使 offline/、runtime/WebView2StandaloneX64.exe、源码就位
# 2. 建 .venv 并装齐依赖（pip --no-index --find-links offline/wheels）
python scripts/setup_venv_offline.py
# 3. 离线装 npm 依赖（走 offline/npm 缓存）
npm ci --offline --ignore-scripts --cache offline/npm
npm ci --prefix gui --offline --ignore-scripts --cache offline/npm
# 4. 构建便携包（build.py 优先用 offline/node/node.exe）
python scripts/build.py
```

前置：内网构建机需已装 Python 3.13（`setup_venv_offline.py` 用它建 venv）与 npm 可执行文件（npm 本身不联网，`--offline` 全走缓存）。

## 未来新增依赖：同步工作流

**加 Python 依赖**（应用运行时）：改 `requirements.txt` → 重新生成 `requirements.lock.txt`（`pip freeze`）→ `python scripts/refresh_offline.py`。

**预置未来/可选 Python 包**：直接往 `requirements-optional.txt` 增删 → `python scripts/refresh_offline.py`。

**加 npm 依赖**：改 `package.json`（根或 `gui/`）→ `npm install` 更新对应 lockfile → `python scripts/refresh_offline.py`。

任何上述文件变化后，`check_offline.py` 都会以退出码 1 提示「依赖已变，先跑 refresh_offline.py」；CI 的构建门禁会因此失败，防止「改了依赖忘了同步离线物料」。

## 可选依赖说明

`requirements-optional.txt` 里的包不会装进应用运行时（PyInstaller 只冻结 `requirements.lock.txt` + 导入图），但已预置进 wheelhouse，内网按需 `pip install --no-index --find-links offline/wheels <包名>` 即可：

- 代码已按需引用：`polars`（data_toolkit 引擎）、`pymysql`（MySQL）、`pyodbc`（SQL Server）。
- 预期扩展：`sqlalchemy`、`psycopg2-binary`、`pymongo`、`python-docx`、`pypdf`、`xlrd`、`matplotlib`、`scipy`、`openai`、`anthropic`、`PyYAML`、`orjson`、`tqdm`、`charset-normalizer`。

**注意**：`pyodbc` 只是绑定，仍需 Windows 系统安装 Microsoft ODBC Driver（17/18），这是系统级前置、不属 pip 依赖。
