"""Intranet software-update check against an nginx-served version manifest.

The app ships as a portable directory distributed through an intranet nginx file
server. This module is the single place that talks HTTP for updates: it fetches a
small ``latest.json`` manifest, compares the server version against the running
app's version, and returns a "new version available" hint with the intranet
download URL. It never downloads or applies anything — a human re-extracts the
package, matching the offline/portable delivery model.

HTTP posture mirrors :mod:`assistant.model_registry`: ``trust_env=False`` (ignore
proxy env), ``follow_redirects=False``, and no request at all when no URL is set.
"""
import os
from urllib.parse import urlparse

import httpx

UPDATE_URL_ENV = "EXCEL_ASSISTANT_UPDATE_URL"
DEFAULT_UPDATE_BASE_URL = ""  # 打包默认；IT 打包前可改为实际内网地址


def validate_update_url(base):
    base = (base or "").strip()
    if not base:
        return base
    parsed = urlparse(base)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("请输入内网 HTTP(S) 更新服务地址")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("更新服务地址不能包含账户信息、查询参数或片段")
    return base.rstrip("/")


def resolve_base_url(user_value):
    """面板保存值 > 环境变量 EXCEL_ASSISTANT_UPDATE_URL > 打包默认常量。"""
    user_value = (user_value or "").strip()
    if user_value:
        return user_value.rstrip("/")
    env_value = os.environ.get(UPDATE_URL_ENV, "").strip()
    if env_value:
        return env_value.rstrip("/")
    return DEFAULT_UPDATE_BASE_URL.strip().rstrip("/")


def _parse_version(version):
    """Return a comparable ``(numbers, stage)`` tuple for a semver-ish string, else None.

    ``stage`` is 1 for a release and 0 for a pre-release, so the same numeric
    version with ``-rc`` sorts before the final release. Build metadata (``+...``)
    is ignored.
    """
    version = (version or "").strip()
    if not version:
        return None
    if "+" in version:
        version = version.split("+", 1)[0]
    pre = None
    if "-" in version:
        version, pre = version.split("-", 1)
    try:
        numbers = [int(p) for p in version.split(".")]
    except ValueError:
        return None
    if not numbers or any(n < 0 for n in numbers):
        return None
    while len(numbers) < 3:
        numbers.append(0)
    return (tuple(numbers), 0 if pre else 1)


def is_newer(latest, current):
    latest_parsed = _parse_version(latest)
    current_parsed = _parse_version(current)
    if latest_parsed is None or current_parsed is None:
        return False
    return latest_parsed > current_parsed


def _resolve_asset_url(base_url, asset_url):
    parsed = urlparse(asset_url)
    if parsed.scheme in {"http", "https"} and parsed.hostname:
        return asset_url
    return base_url.rstrip("/") + "/" + asset_url.lstrip("/")


def check_update(base_url, current_version, timeout=4.0):
    """Return a status dict; never raises for network/parse failures.

    ``update_available`` is True only when the server version is newer. On any
    problem the dict carries ``reason`` (known state) or ``error`` (failure) and
    ``update_available`` stays False, so startup/UI never breaks on a bad update
    server.
    """
    base_url = (base_url or "").strip()
    result = {"update_available": False, "current_version": current_version or ""}
    if not base_url:
        result["reason"] = "未配置更新服务地址"
        return result
    try:
        with httpx.Client(timeout=timeout, trust_env=False, follow_redirects=False) as client:
            response = client.get(base_url.rstrip("/") + "/latest.json")
    except httpx.TimeoutException:
        result["error"] = "更新服务请求超时"
        return result
    except httpx.TransportError:
        result["error"] = "更新服务连接失败，请检查内网地址与防火墙"
        return result
    if response.status_code != 200:
        result["error"] = f"更新服务返回 HTTP {response.status_code}"
        return result
    try:
        manifest = response.json()
    except ValueError:
        result["error"] = "更新清单不是有效 JSON"
        return result
    if not isinstance(manifest, dict):
        result["error"] = "更新清单格式不正确"
        return result
    latest_version = manifest.get("version")
    asset = manifest.get("asset")
    if not isinstance(latest_version, str) or not latest_version.strip():
        result["error"] = "更新清单缺少版本号"
        return result
    if not isinstance(asset, dict) or not isinstance(asset.get("url"), str) or not asset["url"].strip():
        result["error"] = "更新清单缺少下载文件地址"
        return result
    result["latest_version"] = latest_version.strip()
    result["published_at"] = manifest.get("published_at") or ""
    result["notes"] = manifest.get("notes") or ""
    result["sha256"] = (asset.get("sha256") or "").strip()
    result["size_bytes"] = asset.get("size_bytes")
    result["url"] = _resolve_asset_url(base_url, asset["url"].strip())
    if is_newer(latest_version, current_version):
        result["update_available"] = True
    else:
        result["reason"] = "已是最新版本"
    return result
