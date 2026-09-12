from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .models import ToolkitError


DEFAULT_THRESHOLD_BYTES = 50 * 1024 * 1024
EXCEL_SUFFIXES = {".xlsx", ".xls", ".xlsb", ".ods"}
FAST_SUFFIXES = {".csv", ".tsv", ".parquet"}


def choose_engine(
    command: str,
    paths: Iterable[str | Path],
    requested: str = "auto",
    *,
    threshold_bytes: int = DEFAULT_THRESHOLD_BYTES,
) -> str:
    requested = requested.lower()
    if requested not in {"auto", "pandas", "polars"}:
        raise ToolkitError("--engine 仅支持 auto、pandas 或 polars")
    if command == "sql":
        return "duckdb"
    file_paths = [Path(path) for path in paths]
    if requested != "auto":
        if requested == "polars" and any(path.suffix.lower() in EXCEL_SUFFIXES for path in file_paths):
            return "pandas"
        return requested
    if any(path.suffix.lower() in EXCEL_SUFFIXES for path in file_paths):
        return "pandas"
    if file_paths and all(path.suffix.lower() in FAST_SUFFIXES for path in file_paths):
        total_size = sum(path.stat().st_size for path in file_paths if path.exists())
        if total_size >= threshold_bytes:
            return "polars"
    return "pandas"
