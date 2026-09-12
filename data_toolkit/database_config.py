from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .models import ToolkitError


SQLSERVER_DRIVER_18 = "ODBC Driver 18 for SQL Server"
SQLSERVER_DRIVER_17 = "ODBC Driver 17 for SQL Server"
SUPPORTED_SQLSERVER_DRIVERS = (SQLSERVER_DRIVER_18, SQLSERVER_DRIVER_17)
MYSQL_SSL_MODES = {"preferred", "required", "verify_ca", "verify_identity", "disabled"}

COMMON_FIELDS = {
    "$schema",
    "schema_version",
    "type",
    "host",
    "port",
    "database",
    "username",
    "password",
    "password_env",
    "connect_timeout_seconds",
    "query_timeout_seconds",
}
MYSQL_FIELDS = {"charset", "ssl_mode", "ssl_ca", "ssl_cert", "ssl_key"}
SQLSERVER_FIELDS = {
    "authentication",
    "driver",
    "encrypt",
    "trust_server_certificate",
}


@dataclass(frozen=True, slots=True)
class DatabaseConfig:
    type: str
    host: str
    port: int
    database: str
    username: str | None
    password: str | None
    password_source: str | None
    connect_timeout_seconds: int
    query_timeout_seconds: int
    charset: str = "utf8mb4"
    ssl_mode: str = "preferred"
    ssl_ca: str | None = None
    ssl_cert: str | None = None
    ssl_key: str | None = None
    authentication: str = "sql_password"
    driver: str = "auto"
    encrypt: bool = True
    trust_server_certificate: bool = False


def _required_text(data: Mapping[str, object], name: str) -> str:
    value = data.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ToolkitError(f"数据库配置 {name} 必须是非空字符串")
    return value.strip()


def _optional_text(data: Mapping[str, object], name: str) -> str | None:
    value = data.get(name)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ToolkitError(f"数据库配置 {name} 必须是非空字符串或 null")
    return value.strip()


def _integer(data: Mapping[str, object], name: str, default: int, minimum: int, maximum: int) -> int:
    value = data.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ToolkitError(f"数据库配置 {name} 必须是 {minimum}–{maximum} 的整数")
    return value


def _boolean(data: Mapping[str, object], name: str, default: bool) -> bool:
    value = data.get(name, default)
    if not isinstance(value, bool):
        raise ToolkitError(f"数据库配置 {name} 必须是 true 或 false")
    return value


def parse_database_config(
    raw: Mapping[str, object], *, environ: Mapping[str, str] | None = None
) -> DatabaseConfig:
    if not isinstance(raw, Mapping):
        raise ToolkitError("数据库连接配置根节点必须是 JSON 对象")
    if raw.get("schema_version") != 1:
        raise ToolkitError("数据库连接配置 schema_version 必须为 1")
    database_type = str(raw.get("type", "")).casefold()
    if database_type not in {"mysql", "sqlserver"}:
        raise ToolkitError("数据库配置 type 只支持 mysql 或 sqlserver")
    allowed = COMMON_FIELDS | (MYSQL_FIELDS if database_type == "mysql" else SQLSERVER_FIELDS)
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ToolkitError(f"数据库配置包含未知配置项: {', '.join(unknown)}")

    host = _required_text(raw, "host")
    database = _required_text(raw, "database")
    authentication = str(raw.get("authentication", "sql_password")).casefold()
    if database_type == "mysql":
        authentication = "password"
    elif authentication not in {"sql_password", "windows_integrated"}:
        raise ToolkitError("SQL Server authentication 只支持 sql_password 或 windows_integrated")

    username = _optional_text(raw, "username")
    plain_password = _optional_text(raw, "password")
    password_env = _optional_text(raw, "password_env")
    environment = os.environ if environ is None else environ
    environment_password = environment.get(password_env) if password_env else None
    password = environment_password if environment_password not in {None, ""} else plain_password
    password_source = "environment" if environment_password not in {None, ""} else ("config" if plain_password else None)
    if authentication != "windows_integrated":
        if not username:
            raise ToolkitError("密码认证必须提供数据库用户名 username")
        if password is None:
            raise ToolkitError("密码认证必须提供 password，或通过 password_env 指定环境变量")

    ssl_mode = str(raw.get("ssl_mode", "preferred")).casefold()
    if database_type == "mysql" and ssl_mode not in MYSQL_SSL_MODES:
        raise ToolkitError(f"MySQL ssl_mode 不支持: {ssl_mode}")
    ssl_paths = {name: _optional_text(raw, name) for name in ("ssl_ca", "ssl_cert", "ssl_key")}
    for name, value in ssl_paths.items():
        if value and not Path(value).is_file():
            raise ToolkitError(f"MySQL TLS 文件不存在 {name}: {value}")
    if database_type == "mysql" and ssl_mode in {"verify_ca", "verify_identity"} and not ssl_paths["ssl_ca"]:
        raise ToolkitError(f"MySQL ssl_mode={ssl_mode} 时必须提供 ssl_ca")

    driver = str(raw.get("driver", "auto"))
    if database_type == "sqlserver" and driver not in {"auto", *SUPPORTED_SQLSERVER_DRIVERS}:
        raise ToolkitError("SQL Server driver 只支持 auto、ODBC Driver 18 或 ODBC Driver 17")

    return DatabaseConfig(
        type=database_type,
        host=host,
        port=_integer(raw, "port", 3306 if database_type == "mysql" else 1433, 1, 65535),
        database=database,
        username=username,
        password=password,
        password_source=password_source,
        connect_timeout_seconds=_integer(raw, "connect_timeout_seconds", 15, 1, 300),
        query_timeout_seconds=_integer(raw, "query_timeout_seconds", 600, 1, 86_400),
        charset=str(raw.get("charset", "utf8mb4")),
        ssl_mode=ssl_mode,
        ssl_ca=ssl_paths["ssl_ca"],
        ssl_cert=ssl_paths["ssl_cert"],
        ssl_key=ssl_paths["ssl_key"],
        authentication=authentication,
        driver=driver,
        encrypt=_boolean(raw, "encrypt", True),
        trust_server_certificate=_boolean(raw, "trust_server_certificate", False),
    )


def load_database_config(path: str | Path) -> DatabaseConfig:
    source = Path(path)
    if not source.is_file():
        raise ToolkitError(f"数据库连接配置不存在: {source}")
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ToolkitError(f"读取数据库连接配置失败 {source}: {exc}") from exc
    return parse_database_config(value)


def detect_sql_server_driver(available_drivers: list[str], configured: str = "auto") -> str:
    available = set(available_drivers)
    if configured == "auto":
        for candidate in SUPPORTED_SQLSERVER_DRIVERS:
            if candidate in available:
                return candidate
        raise ToolkitError(
            "未检测到 Microsoft ODBC Driver 17/18 for SQL Server；"
            "客户环境至少需要安装 ODBC Driver 17 for SQL Server"
        )
    if configured not in SUPPORTED_SQLSERVER_DRIVERS:
        raise ToolkitError(f"不允许使用 SQL Server ODBC 驱动: {configured}")
    if configured not in available:
        raise ToolkitError(f"未安装配置指定的 SQL Server ODBC 驱动: {configured}")
    return configured


def _odbc_value(value: object) -> str:
    return "{" + str(value).replace("}", "}}") + "}"


def sqlserver_connection_string(
    config: DatabaseConfig, *, available_drivers: list[str]
) -> str:
    if config.type != "sqlserver":
        raise ToolkitError("仅 SQL Server 配置可以生成 ODBC 连接串")
    driver = detect_sql_server_driver(available_drivers, config.driver)
    parts = [
        f"DRIVER={_odbc_value(driver)}",
        f"SERVER={_odbc_value(f'tcp:{config.host},{config.port}')}",
        f"DATABASE={_odbc_value(config.database)}",
    ]
    if config.authentication == "windows_integrated":
        parts.append("Trusted_Connection=yes")
    else:
        parts.extend(
            [
                f"UID={_odbc_value(config.username or '')}",
                f"PWD={_odbc_value(config.password or '')}",
            ]
        )
    parts.extend(
        [
            f"Encrypt={'yes' if config.encrypt else 'no'}",
            f"TrustServerCertificate={'yes' if config.trust_server_certificate else 'no'}",
            "ApplicationIntent=ReadOnly",
            f"APP={_odbc_value('Kingdee BOM Data Toolkit')}",
        ]
    )
    return ";".join(parts) + ";"
