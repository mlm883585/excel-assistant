from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .database_config import DatabaseConfig, sqlserver_connection_string
from .models import ToolkitError
from .sql_runner import bind_named_parameters, validate_database_sql


def redact_database_error(error: BaseException, config: DatabaseConfig) -> str:
    message = str(error)
    for secret in (config.password,):
        if secret:
            message = message.replace(secret, "***")
    return message


@dataclass(slots=True)
class DatabaseSession:
    connection: Any
    database_type: str
    placeholder: str
    driver: str | None = None
    query_timeout_seconds: int = 600
    secrets: tuple[str, ...] = ()

    def __enter__(self) -> "DatabaseSession":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def close(self) -> None:
        try:
            self.connection.rollback()
        finally:
            self.connection.close()

    def execute(
        self,
        query: str,
        parameters: Mapping[str, object] | None = None,
        *,
        trusted: bool = False,
    ) -> Any:
        statement = query.strip() if trusted else validate_database_sql(query)
        sql, values = bind_named_parameters(
            statement, parameters or {}, placeholder=self.placeholder
        )
        cursor = self.connection.cursor()
        try:
            if hasattr(cursor, "timeout"):
                cursor.timeout = self.query_timeout_seconds
            cursor.execute(sql, values)
            return cursor
        except Exception as exc:
            try:
                cursor.close()
            except Exception:
                pass
            message = str(exc)
            for secret in self.secrets:
                if secret:
                    message = message.replace(secret, "***")
            raise ToolkitError(f"数据库查询失败: {message}") from exc


def _mysql_connect_kwargs(config: DatabaseConfig, pymysql: Any) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "host": config.host,
        "port": config.port,
        "user": config.username,
        "password": config.password,
        "database": config.database,
        "charset": config.charset,
        "autocommit": False,
        "connect_timeout": config.connect_timeout_seconds,
        "read_timeout": config.query_timeout_seconds,
        "write_timeout": config.query_timeout_seconds,
        "cursorclass": pymysql.cursors.SSCursor,
    }
    if config.ssl_mode == "disabled":
        kwargs["ssl_disabled"] = True
    else:
        kwargs["ssl_disabled"] = False
        ssl_options: dict[str, object] = {}
        if config.ssl_ca:
            ssl_options["ca"] = config.ssl_ca
        if config.ssl_cert:
            ssl_options["cert"] = config.ssl_cert
        if config.ssl_key:
            ssl_options["key"] = config.ssl_key
        if config.ssl_mode in {"required", "verify_ca", "verify_identity"}:
            ssl_options["check_hostname"] = config.ssl_mode == "verify_identity"
            ssl_options["verify_mode"] = (
                "required" if config.ssl_mode in {"verify_ca", "verify_identity"} else "none"
            )
        if ssl_options:
            kwargs["ssl"] = ssl_options
    return kwargs


def connect_database(config: DatabaseConfig) -> DatabaseSession:
    try:
        if config.type == "mysql":
            try:
                import pymysql
            except ImportError as exc:
                raise ToolkitError("MySQL 查询需要安装 database 依赖档（PyMySQL）") from exc
            connection = pymysql.connect(**_mysql_connect_kwargs(config, pymysql))
            setup_cursor = connection.cursor()
            try:
                setup_cursor.execute("SET SESSION TRANSACTION READ ONLY")
                setup_cursor.execute("START TRANSACTION READ ONLY")
            finally:
                setup_cursor.close()
            return DatabaseSession(
                connection,
                database_type="mysql",
                placeholder="%s",
                query_timeout_seconds=config.query_timeout_seconds,
                secrets=tuple(secret for secret in (config.password,) if secret),
            )

        try:
            import pyodbc
        except ImportError as exc:
            raise ToolkitError("SQL Server 查询需要安装 database 依赖档（pyodbc）") from exc
        driver = None
        connection_string = sqlserver_connection_string(
            config, available_drivers=list(pyodbc.drivers())
        )
        # Resolve once more for audit metadata without ever exposing the full string.
        from .database_config import detect_sql_server_driver

        driver = detect_sql_server_driver(list(pyodbc.drivers()), config.driver)
        connection = pyodbc.connect(
            connection_string,
            timeout=config.connect_timeout_seconds,
            autocommit=False,
        )
        connection.timeout = config.query_timeout_seconds
        return DatabaseSession(
            connection,
            database_type="sqlserver",
            placeholder="?",
            driver=driver,
            query_timeout_seconds=config.query_timeout_seconds,
            secrets=tuple(secret for secret in (config.password,) if secret),
        )
    except ToolkitError:
        raise
    except Exception as exc:
        raise ToolkitError(f"数据库连接失败: {redact_database_error(exc, config)}") from exc


def check_database(config: DatabaseConfig) -> dict[str, object]:
    try:
        with connect_database(config) as session:
            cursor = session.execute("SELECT 1 AS connection_test")
            row = cursor.fetchone()
            cursor.close()
            if row is None or int(row[0]) != 1:
                raise ToolkitError("数据库连接检查未返回预期结果")
            return {
                "type": config.type,
                "host": config.host,
                "port": config.port,
                "database": config.database,
                "driver": session.driver,
            }
    except ToolkitError:
        raise
    except Exception as exc:
        raise ToolkitError(f"数据库连接检查失败: {redact_database_error(exc, config)}") from exc
