# 内网软件更新服务

应用是**便携包目录**（`build/ExcelAssistant/`，`scripts/build.py` 产出，无安装器）。内网更新走「nginx 托管版本清单 + 安装包」，应用侧**检查 → 提示 → 人工下载替换**，不自动下载、不自动改动本机，与离线/便携交付模型一致。

## 一、服务端

### 目录布局

```
<update_root>/                          # 例：D:\updates\ExcelAssistant（nginx root）
  latest.json                           # 版本清单（客户端轮询的唯一入口）
  ExcelAssistant-0.2.0-win64.zip        # 完整便携包（顶层含 ExcelAssistant 文件夹）
  ExcelAssistant-0.1.0-win64.zip        # 保留历史版本，便于回退
  corresponding-source.zip              # 可选：对应源码（审计）
```

### 版本清单 `latest.json`

```json
{
  "name": "ExcelAssistant",
  "version": "0.2.0",
  "channel": "stable",
  "published_at": "2026-09-20T10:00:00+08:00",
  "notes": "新增 …；修复 …（纯文本，可含换行）",
  "asset": {
    "url": "ExcelAssistant-0.2.0-win64.zip",
    "sha256": "<zip 的 64 位十六进制 SHA-256>",
    "size_bytes": 417333248
  }
}
```

`asset.url` 支持相对路径（相对 `base_url` 解析）或绝对内网 URL。`sha256` 供展示与未来自动下载校验，本次人工流程仍写入保证可追溯。

### nginx

示例配置见 [`deploy/nginx/update.conf`](../deploy/nginx/update.conf)。要点：

- `location = /latest.json`（精确匹配优先级最高）禁止缓存，保证客户端取到最新清单。
- `~* \.(zip|sha256)$` 对不可变安装包长缓存（文件名带版本号）。
- 按需放开 `allow/deny` 内网网段限制；日志用于审计下载记录。

可选 HTTPS / 基础认证：在 `server` 块加

```nginx
    # 基础认证（客户端需带账密时，应用侧要另行支持）
    # auth_basic "ExcelAssistant Update";
    # auth_basic_user_file conf/htpasswd_update;
```

HTTPS 需自签/内网 CA 证书并配置 `ssl_certificate`/`ssl_certificate_key`；客户端应用使用 `follow_redirects=False`、不校验证书链以外的配置，仅认 `http(s)` 地址。

### 发布脚本

```bash
python scripts/stage_update.py --version 0.2.0 --notes-file release-notes.md --out build/update-release
```

产出 `latest.json` + `ExcelAssistant-0.2.0-win64.zip`（并复制 `manifest.sha256.json`、`corresponding-source.zip`）。把二者拷入 nginx `root` 即完成发布。

## 二、应用侧

- **版本来源**：`ppx.toml:4` `version`，运行时 `main.py` 注入 `api.set_app_version(app.settings.project.version)`。
- **更新地址解析**：`assistant/update_service.py::resolve_base_url` —— 面板保存值 > 环境变量 `EXCEL_ASSISTANT_UPDATE_URL` > 打包默认常量 `DEFAULT_UPDATE_BASE_URL`（IT 打包前可改）。留空即完全离线，不发任何请求。
- **检查**：`api/api.py` `update.check` → `check_update()` 拉取 `latest.json`、比较 semver。失败/无地址/无更新均静默，不打断启动。
- **HTTP 约束**：`httpx.Client(trust_env=False, follow_redirects=False)`，与模型端点一致，不外呼。
- **界面**：「设置与环境 → 软件更新」tab：当前版本、更新服务地址、保存、检查更新、发现新版展示下载地址 + 复制；启动时后台静默检查，发现新版弹通知。

## 三、回退与排障

- **回退**：保留历史版本 zip；把 `latest.json` 的 `version` 改回旧版即让客户端不再提示，或直接重新解压旧包。
- **客户端不提示**：确认面板更新地址 / `EXCEL_ASSISTANT_UPDATE_URL` 指向的 nginx 根目录里有 `latest.json` 且 `version` 高于 `ppx.toml`；`curl http://<host>/latest.json` 核对。
- **一致校验**：发布侧需保证 `latest.json.version` 与包内 `_internal/ppx.toml` 的 `version` 一致（后续可在 `stage_update.py` 增加校验）。

## 已知限制（v1）

- 仅「检查 + 提示 + 人工下载替换」，不做自动下载/自替换（便携包运行中文件占用需独立 updater 进程，留待后续）。
- 检查在应用启动/手动触发，非定时轮询；无内网地址时完全离线（行为等同现状）。
