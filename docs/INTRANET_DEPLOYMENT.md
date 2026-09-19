# 内网部署手册

面向交付给无外网内网环境的两类物料，本手册给出**最小部署步骤**。目标是：内网机器**零代码改动、零网络**即可运行，仅需一次性配置。

## 交付物料

| 物料 | 用途 |
| --- | --- |
| `build/ExcelAssistant.zip` | **主交付**：预构建、已全量验证的便携应用，解压即运行 |
| `build/offline-build-kit.zip` | **备用**：零网络重建套件（未来内网热修复/改版时用） |

## 一、主路径：解压即运行（零代码改动）

1. **拷贝解压**：把 `ExcelAssistant.zip` 拷入内网目标机并解压到任意目录（免 Python / Node / pip / npm）。

2. **系统前置**（常规 Windows 环境已满足）：
   - Windows 10/11 x64；
   - .NET Framework 4.6.2+（Win10/11 自带，无需单独安装）；
   - 可写的数据目录（默认 `%LOCALAPPDATA%\ExcelAssistant`，可用 env `EXCEL_ASSISTANT_HOME` 改）。

3. **WebView2 Runtime**：首次运行前，由 IT 运行随包安装器 `prerequisites/WebView2StandaloneX64.exe`（或 IT 已统一装好 WebView2 Runtime）。该安装器经 Microsoft 签名验证。

4. **可选功能前置**（按需，非核心链路必需）：
   - **原生 Excel 重算**：需目标机安装 Microsoft Office/Excel。
   - **SQL Server 数据源**：需安装 Microsoft ODBC Driver 17/18 for SQL Server（系统级，IT 安装）。

5. **一次性配置模型端点**：双击 `ExcelAssistant.exe` 启动，在「环境」面板填写内网模型服务：
   - `base_url`：内网 OpenAI 兼容端点（如 `http://<内网模型服务>/v1`）；
   - `model`：模型名；
   - 若端点需鉴权，由 IT 通过环境变量 `EXCEL_ASSISTANT_API_KEY` 注入（**密钥只走环境变量，绝不写入配置文件**）；备用端点用 `EXCEL_ASSISTANT_FALLBACK_API_KEY`。

6. **（可选）内网更新服务**：如在内网 nginx 部署更新，IT 设 env `EXCEL_ASSISTANT_UPDATE_URL` 或在「环境」面板填更新地址；发布流程见 `docs/UPDATE_SERVICE.md`。

7. **开始使用**：模型配置保存后即进入对话，无需任何代码改动。

## 二、备用路径：内网零网络重建

当内网需要改代码后重新打包（不依赖外网）时，解压 `offline-build-kit.zip`，在本机（需 Python 3.13 + Node，见 `docs/OFFLINE_DELIVERY.md`）执行：

```powershell
python scripts/setup_venv_offline.py
npm ci --offline --ignore-scripts --cache offline/npm
npm ci --prefix gui --offline --ignore-scripts --cache offline/npm
python scripts/build.py
```

详见 `docs/OFFLINE_DELIVERY.md` 的内网重建步骤与依赖同步机制。

## 三、交付验收

内网验收项见随包 `OFFLINE_ACCEPTANCE.md`；运行时诊断可在「环境」面板查看（.NET / WebView2 / 数据目录 / 模型连通性）。
