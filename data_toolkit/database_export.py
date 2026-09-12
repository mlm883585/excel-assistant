from __future__ import annotations

import math
import os
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd

from .models import ToolkitError


EXCEL_MAX_DATA_ROWS = 1_048_575
SUPPORTED_OUTPUTS = {".xlsx", ".csv", ".tsv", ".parquet"}


@dataclass(frozen=True, slots=True)
class SpoolResult:
    path: Path
    columns: tuple[str, ...]
    row_count: int
    chunk_count: int


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _validate_columns(cursor: Any) -> tuple[str, ...]:
    if not cursor.description:
        raise ToolkitError("数据库查询没有返回结果集")
    columns = tuple(str(item[0]).strip() if item[0] is not None else "" for item in cursor.description)
    if any(not column for column in columns):
        raise ToolkitError("数据库查询结果包含空字段名，请为表达式设置别名")
    folded = [column.casefold() for column in columns]
    duplicates = sorted({column for column in folded if folded.count(column) > 1})
    if duplicates:
        raise ToolkitError(f"数据库查询结果包含重复字段名: {', '.join(duplicates)}")
    return columns


def spool_cursor(cursor: Any, temp_directory: Path, *, chunk_size: int) -> SpoolResult:
    if not 1_000 <= chunk_size <= 500_000 and chunk_size not in {1, 2, 3}:
        # Tiny sizes are intentionally accepted for deterministic unit tests.
        raise ToolkitError("chunk-size 必须在 1000–500000 之间")
    columns = _validate_columns(cursor)
    folder = Path(temp_directory)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"database-query-{uuid4().hex}.duckdb"
    import duckdb

    connection = duckdb.connect(str(path))
    row_count = 0
    chunk_count = 0
    created = False
    try:
        while True:
            rows = cursor.fetchmany(chunk_size)
            if not rows:
                break
            frame = pd.DataFrame.from_records(rows, columns=columns)
            connection.register("incoming_chunk", frame)
            try:
                if not created:
                    connection.execute("CREATE TABLE query_result AS SELECT * FROM incoming_chunk")
                    created = True
                else:
                    connection.execute("INSERT INTO query_result SELECT * FROM incoming_chunk")
            finally:
                connection.unregister("incoming_chunk")
            row_count += len(rows)
            chunk_count += 1
        if not created:
            definitions = ", ".join(f"{_quote_identifier(column)} VARCHAR" for column in columns)
            connection.execute(f"CREATE TABLE query_result ({definitions})")
        connection.execute("CHECKPOINT")
        return SpoolResult(path, columns, row_count, chunk_count)
    except Exception as exc:
        connection.close()
        path.unlink(missing_ok=True)
        if isinstance(exc, ToolkitError):
            raise
        raise ToolkitError(f"暂存数据库查询结果失败: {exc}") from exc
    finally:
        try:
            connection.close()
        except Exception:
            pass


def profile_spool(spool: SpoolResult) -> pd.DataFrame:
    import duckdb

    connection = duckdb.connect(str(spool.path), read_only=True)
    try:
        types = {
            row[0]: row[1]
            for row in connection.execute("DESCRIBE query_result").fetchall()
        }
        rows: list[dict[str, object]] = []
        for column in spool.columns:
            quoted = _quote_identifier(column)
            nulls, unique_values = connection.execute(
                f"SELECT COUNT(*) - COUNT({quoted}), COUNT(DISTINCT {quoted}) FROM query_result"
            ).fetchone()
            minimum = maximum = None
            try:
                minimum, maximum = connection.execute(
                    f"SELECT MIN({quoted}), MAX({quoted}) FROM query_result"
                ).fetchone()
            except Exception:
                pass
            rows.append(
                {
                    "字段": column,
                    "数据类型": types.get(column, "UNKNOWN"),
                    "记录数": spool.row_count,
                    "空值数": int(nulls),
                    "空值率%": round(int(nulls) / spool.row_count * 100, 4) if spool.row_count else 0,
                    "唯一值数": int(unique_values),
                    "重复值数": max(0, spool.row_count - int(nulls) - int(unique_values)),
                    "最小值": minimum,
                    "最大值": maximum,
                }
            )
        return pd.DataFrame(rows)
    finally:
        connection.close()


def _temporary_output(output: Path) -> Path:
    if output.exists():
        raise ToolkitError(f"输出文件已存在，拒绝覆盖: {output}")
    if output.suffix.casefold() not in SUPPORTED_OUTPUTS:
        raise ToolkitError(f"不支持的数据库查询输出格式: {output.suffix}")
    output.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(
        prefix=f".{output.stem}.", suffix=output.suffix, dir=output.parent
    )
    os.close(handle)
    temp = Path(name)
    temp.unlink()
    return temp


def _duckdb_path(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def _excel_value(value: object) -> object:
    if isinstance(value, memoryview):
        return bytes(value).hex().upper()
    if isinstance(value, bytes):
        return value.hex().upper()
    if isinstance(value, (datetime, date, time, Decimal, str, int, float, bool)) or value is None:
        return value
    return str(value)


def _write_xlsx(spool: SpoolResult, temp: Path) -> None:
    import duckdb
    import xlsxwriter

    connection = duckdb.connect(str(spool.path), read_only=True)
    workbook = xlsxwriter.Workbook(
        str(temp),
        {
            "constant_memory": True,
            "strings_to_formulas": False,
            "strings_to_urls": False,
        },
    )
    try:
        header_format = workbook.add_format(
            {"bold": True, "bg_color": "#1F4E78", "font_color": "#FFFFFF", "border": 1}
        )
        total_sheets = max(1, math.ceil(spool.row_count / EXCEL_MAX_DATA_ROWS))
        cursor = connection.execute("SELECT * FROM query_result")
        for sheet_number in range(1, total_sheets + 1):
            name = "数据" if total_sheets == 1 else f"数据_{sheet_number:03d}"
            worksheet = workbook.add_worksheet(name)
            worksheet.freeze_panes(1, 0)
            for column_index, column in enumerate(spool.columns):
                worksheet.write_string(0, column_index, column, header_format)
                worksheet.set_column(column_index, column_index, min(40, max(10, len(column) * 2 + 2)))
            written = 0
            while written < EXCEL_MAX_DATA_ROWS:
                batch = cursor.fetchmany(min(10_000, EXCEL_MAX_DATA_ROWS - written))
                if not batch:
                    break
                for row in batch:
                    for column_index, value in enumerate(row):
                        worksheet.write(written + 1, column_index, _excel_value(value))
                    written += 1
            if spool.columns:
                worksheet.autofilter(0, 0, max(written, 1), len(spool.columns) - 1)
        workbook.close()
    except Exception:
        try:
            workbook.close()
        except Exception:
            pass
        raise
    finally:
        connection.close()


def export_spool(spool: SpoolResult, path: str | Path) -> Path:
    output = Path(path)
    temp = _temporary_output(output)
    import duckdb

    try:
        suffix = output.suffix.casefold()
        if suffix == ".xlsx":
            _write_xlsx(spool, temp)
        else:
            connection = duckdb.connect(str(spool.path), read_only=True)
            try:
                target = _duckdb_path(temp)
                if suffix == ".parquet":
                    options = "FORMAT PARQUET"
                else:
                    delimiter = "\\t" if suffix == ".tsv" else ","
                    options = f"FORMAT CSV, HEADER, DELIMITER '{delimiter}'"
                connection.execute(
                    f"COPY (SELECT * FROM query_result) TO '{target}' ({options})"
                )
            finally:
                connection.close()
        os.replace(temp, output)
        return output
    except Exception as exc:
        temp.unlink(missing_ok=True)
        if isinstance(exc, ToolkitError):
            raise
        raise ToolkitError(f"导出数据库查询结果失败 {output}: {exc}") from exc
