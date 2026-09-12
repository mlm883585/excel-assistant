from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Iterable

import pandas as pd

from .models import ToolkitError


SUPPORTED_SUFFIXES = {".xlsx", ".xls", ".xlsb", ".ods", ".csv", ".tsv", ".parquet"}


def _check_input(path: Path) -> None:
    if not path.is_file():
        raise ToolkitError(f"输入文件不存在: {path}")
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ToolkitError(f"不支持的文件格式: {path.suffix}")


def read_table(
    path: str | Path,
    *,
    sheet: str | int | None = None,
    header_row: int | str = "auto",
    engine: str = "pandas",
    encoding: str = "utf-8-sig",
) -> pd.DataFrame:
    source = Path(path)
    _check_input(source)
    suffix = source.suffix.lower()
    header = 0 if header_row == "auto" else int(header_row) - 1
    try:
        if suffix in {".xlsx", ".xls", ".xlsb", ".ods"}:
            if suffix == ".xlsx":
                with source.open("rb") as stream:
                    if stream.read(8) == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
                        raise ToolkitError(f"不支持密码保护文件: {source}")
            selected_sheet = 0 if sheet is None else sheet
            excel_engine = "openpyxl" if suffix == ".xlsx" else "calamine"
            return pd.read_excel(source, sheet_name=selected_sheet, header=header, dtype=object, engine=excel_engine, keep_default_na=False)
        normalized_encoding = encoding.replace("-", "").replace("_", "").casefold()
        use_polars = engine == "polars" and header == 0 and normalized_encoding in {"utf8", "utf8sig"}
        if use_polars:
            import polars as pl

            try:
                if suffix == ".parquet":
                    polars_frame = pl.read_parquet(source)
                else:
                    separator = "\t" if suffix == ".tsv" else ","
                    polars_frame = pl.read_csv(source, separator=separator, infer_schema=False, encoding="utf8")
                return pd.DataFrame(polars_frame.to_dict(as_series=False))
            except Exception:
                # Preserve data instead of using Polars' lossy UTF-8 mode. Pandas
                # supplies the configured/GB18030 decoder fallback below.
                if suffix == ".parquet":
                    raise
        if suffix == ".parquet":
            try:
                import polars as pl
            except ImportError as exc:
                raise ToolkitError("读取 Parquet 需要 Polars") from exc
            return pd.DataFrame(pl.read_parquet(source).to_dict(as_series=False))
        separator = "\t" if suffix == ".tsv" else ","
        try:
            return pd.read_csv(source, sep=separator, header=header, dtype=str, keep_default_na=False, encoding=encoding)
        except UnicodeDecodeError:
            if normalized_encoding not in {"utf8", "utf8sig"}:
                raise
            return pd.read_csv(source, sep=separator, header=header, dtype=str, keep_default_na=False, encoding="gb18030")
    except ToolkitError:
        raise
    except Exception as exc:
        message = str(exc)
        if "password" in message.casefold() or "encrypted" in message.casefold():
            raise ToolkitError(f"不支持密码保护文件: {source}") from exc
        raise ToolkitError(f"读取文件失败 {source}: {exc}") from exc


def _prepare_output(path: Path) -> Path:
    if path.exists():
        raise ToolkitError(f"输出文件已存在，拒绝覆盖: {path}")
    if path.suffix.lower() not in {".xlsx", ".csv", ".tsv", ".parquet"}:
        raise ToolkitError(f"不支持的输出格式: {path.suffix}")
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=path.suffix, dir=path.parent)
    os.close(handle)
    temp = Path(name)
    temp.unlink()
    return temp


def _serializable_frame(frame: pd.DataFrame, id_columns: Iterable[str]) -> pd.DataFrame:
    data = frame.copy()
    for column in id_columns:
        if column in data.columns:
            data[column] = data[column].map(lambda value: "" if pd.isna(value) else str(value))
    return data


def write_table(frame: pd.DataFrame, path: str | Path, *, id_columns: Iterable[str] = ()) -> Path:
    output = Path(path)
    temp = _prepare_output(output)
    data = _serializable_frame(frame, id_columns)
    try:
        suffix = output.suffix.lower()
        if suffix == ".xlsx":
            with pd.ExcelWriter(
                temp,
                engine="xlsxwriter",
                engine_kwargs={"options": {"strings_to_formulas": False, "strings_to_urls": False}},
            ) as writer:
                data.to_excel(writer, index=False, sheet_name="数据")
                sheet = writer.sheets["数据"]
                sheet.freeze_panes(1, 0)
                if len(data.columns):
                    sheet.autofilter(0, 0, max(len(data), 1), len(data.columns) - 1)
                header_format = writer.book.add_format({"bold": True, "bg_color": "#1F4E78", "font_color": "#FFFFFF", "border": 1})
                text_format = writer.book.add_format({"num_format": "@"})
                for index, column in enumerate(data.columns):
                    sheet.write(0, index, column, header_format)
                    width = min(40, max(10, len(str(column)) * 2 + 2))
                    sheet.set_column(index, index, width, text_format if column in set(id_columns) else None)
        elif suffix in {".csv", ".tsv"}:
            data.to_csv(temp, index=False, sep="\t" if suffix == ".tsv" else ",", encoding="utf-8-sig")
        elif suffix == ".parquet":
            import polars as pl

            pl.DataFrame({str(column): data[column].tolist() for column in data.columns}).write_parquet(temp)
        os.replace(temp, output)
        return output
    except Exception as exc:
        temp.unlink(missing_ok=True)
        if isinstance(exc, ToolkitError):
            raise
        raise ToolkitError(f"写入文件失败 {output}: {exc}") from exc
