from __future__ import annotations

import re
from collections.abc import Mapping

import pandas as pd

from .models import ToolkitError


FORBIDDEN_SQL = {
    "alter", "attach", "backup", "bulk", "call", "copy", "create", "dbcc",
    "declare", "delete", "deny", "detach", "drop", "execute", "exec", "export",
    "grant", "import", "insert", "install", "load", "merge", "pragma", "replace",
    "restore", "revoke", "set", "truncate", "update", "use", "waitfor",
}

FORBIDDEN_TABLE_FUNCTIONS = {
    "csv_scan", "glob", "httpfs", "parquet_scan", "postgres_scan", "read_blob",
    "read_csv", "read_csv_auto", "read_json", "read_json_auto", "read_ndjson",
    "read_parquet", "read_text", "read_xlsx", "sqlite_scan",
}


def _mask_non_code(query: str) -> str:
    """Mask strings, quoted identifiers and comments while preserving positions."""
    result = list(query)
    index = 0
    state = "code"
    while index < len(query):
        char = query[index]
        following = query[index + 1] if index + 1 < len(query) else ""
        if state == "code":
            if char == "'":
                state = "single"
                result[index] = " "
            elif char == '"':
                state = "double"
                result[index] = " "
            elif char == "[":
                state = "bracket"
                result[index] = " "
            elif char == "`":
                state = "backtick"
                result[index] = " "
            elif char == "-" and following == "-":
                state = "line_comment"
                result[index] = result[index + 1] = " "
                index += 1
            elif char == "/" and following == "*":
                state = "block_comment"
                result[index] = result[index + 1] = " "
                index += 1
        elif state == "single":
            result[index] = " "
            if char == "'" and following == "'":
                result[index + 1] = " "
                index += 1
            elif char == "'":
                state = "code"
        elif state == "double":
            result[index] = " "
            if char == '"' and following == '"':
                result[index + 1] = " "
                index += 1
            elif char == '"':
                state = "code"
        elif state == "bracket":
            result[index] = " "
            if char == "]" and following == "]":
                result[index + 1] = " "
                index += 1
            elif char == "]":
                state = "code"
        elif state == "backtick":
            result[index] = " "
            if char == "`" and following == "`":
                result[index + 1] = " "
                index += 1
            elif char == "`":
                state = "code"
        elif state == "line_comment":
            result[index] = " " if char not in "\r\n" else char
            if char in "\r\n":
                state = "code"
        elif state == "block_comment":
            result[index] = " " if char not in "\r\n" else char
            if char == "*" and following == "/":
                result[index + 1] = " "
                index += 1
                state = "code"
        index += 1
    if state in {"single", "double", "bracket", "backtick", "block_comment"}:
        raise ToolkitError("SQL 包含未闭合的字符串、标识符或注释")
    return "".join(result)


def _validate_sql(query: str, *, forbid_external_functions: bool) -> str:
    masked = _mask_non_code(query)
    if not masked.strip():
        raise ToolkitError("SQL 查询不能为空")
    semicolons = [match.start() for match in re.finditer(";", masked)]
    if semicolons:
        trailing = masked[semicolons[-1] + 1 :].strip()
        if len(semicolons) != 1 or trailing:
            raise ToolkitError("只允许执行一条 SQL 查询")
        masked = masked[: semicolons[0]]
        query = query[: semicolons[0]]
    statement_mask = masked.strip()
    if not statement_mask:
        raise ToolkitError("只允许执行一条 SQL 查询")
    first = re.match(r"[A-Za-z]+", statement_mask)
    if not first or first.group(0).casefold() not in {"select", "with"}:
        raise ToolkitError("只允许 SELECT 或 WITH 只读查询")
    words = {word.casefold() for word in re.findall(r"\b[A-Za-z_]+\b", statement_mask)}
    blocked = sorted(words & FORBIDDEN_SQL)
    if blocked:
        raise ToolkitError(f"SQL 包含禁止关键字: {', '.join(blocked)}")
    normalized = " ".join(statement_mask.casefold().split())
    blocked_patterns = {
        r"\bselect\b[\s\S]*?\binto\b": "SELECT INTO",
        r"\bfor\s+update\b": "FOR UPDATE",
        r"\block\s+in\s+share\s+mode\b": "LOCK IN SHARE MODE",
        r"\binto\s+(?:out|dump)file\b": "INTO OUTFILE/DUMPFILE",
        r"\bload_file\s*\(": "LOAD_FILE",
        r"\bsleep\s*\(": "SLEEP",
        r"\bbenchmark\s*\(": "BENCHMARK",
        r"\bopenrowset\s*\(": "OPENROWSET",
        r"\bopendatasource\s*\(": "OPENDATASOURCE",
    }
    for pattern, label in blocked_patterns.items():
        if re.search(pattern, normalized, flags=re.IGNORECASE):
            raise ToolkitError(f"SQL 包含禁止操作: {label}")
    if forbid_external_functions:
        external = sorted(words & FORBIDDEN_TABLE_FUNCTIONS)
        if external:
            raise ToolkitError(f"SQL 禁止自行读取外部文件或数据源: {', '.join(external)}")
    return query.strip()


def validate_readonly_sql(query: str) -> str:
    return _validate_sql(query, forbid_external_functions=True)


def validate_database_sql(query: str) -> str:
    return _validate_sql(query, forbid_external_functions=False)


def bind_named_parameters(
    query: str, parameters: Mapping[str, object], *, placeholder: str
) -> tuple[str, list[object]]:
    if placeholder not in {"?", "%s"}:
        raise ValueError("unsupported database placeholder")
    masked = _mask_non_code(query)
    pattern = re.compile(r"(?<!:):([A-Za-z_][A-Za-z0-9_]*)")
    matches = list(pattern.finditer(masked))
    names = [match.group(1) for match in matches]
    missing = sorted(set(names) - set(parameters))
    if missing:
        raise ToolkitError(f"SQL 参数缺少值: {', '.join(missing)}")
    unused = sorted(set(parameters) - set(names))
    if unused:
        raise ToolkitError(f"存在未使用的 SQL 参数: {', '.join(unused)}")
    parts: list[str] = []
    values: list[object] = []
    cursor = 0
    for match in matches:
        parts.append(query[cursor : match.start()])
        parts.append(placeholder)
        values.append(parameters[match.group(1)])
        cursor = match.end()
    parts.append(query[cursor:])
    return "".join(parts), values


def run_query(tables: Mapping[str, pd.DataFrame], query: str) -> pd.DataFrame:
    statement = validate_readonly_sql(query)
    try:
        import duckdb
    except ImportError as exc:
        raise ToolkitError("SQL 关联需要安装 duckdb 依赖档（数据分析扩展）") from exc

    connection = duckdb.connect(database=":memory:", config={"enable_external_access": "false"})
    try:
        for name, frame in tables.items():
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                raise ToolkitError(f"非法表名: {name}")
            connection.register(name, frame)
        return connection.execute(statement).fetchdf()
    except ToolkitError:
        raise
    except Exception as exc:
        raise ToolkitError(f"SQL 执行失败: {exc}") from exc
    finally:
        connection.close()


def coerce_numeric_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with unambiguous numeric string columns cast to numbers,
    protecting leading-zero codes. Lets SQL aggregation (SUM/AVG) work over
    text-typed frames without manual CAST."""
    from pandas.api.types import is_numeric_dtype, is_datetime64_any_dtype

    result = frame.copy()
    for col in result.columns:
        if str(col).startswith('__source_'):
            continue
        series = result[col]
        if is_numeric_dtype(series) or is_datetime64_any_dtype(series):
            continue
        values = series.dropna().astype(str).str.strip()
        non_empty = values[values != '']
        if non_empty.empty:
            continue
        if any(len(v) > 1 and v[0] == '0' and v[1] != '.' for v in non_empty):
            continue  # preserve leading-zero codes
        coerced = pd.to_numeric(non_empty, errors='coerce')
        if coerced.notna().all():
            result[col] = pd.to_numeric(series, errors='coerce')
    return result
