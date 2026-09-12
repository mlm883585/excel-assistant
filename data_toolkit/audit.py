from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from .models import DataIssue, ToolkitError


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_versions() -> dict[str, str]:
    versions: dict[str, str] = {"python": platform.python_version()}
    for package in (
        "pandas", "polars", "duckdb", "pandera", "rapidfuzz", "openpyxl", "xlsxwriter",
        "pymysql", "pyodbc", "cryptography",
    ):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            continue
    return versions


def new_run(command: str, engine: str) -> dict[str, Any]:
    return {
        "run_id": str(uuid4()),
        "command": command,
        "engine": engine,
        "started_at": datetime.now(UTC).isoformat(),
        "versions": package_versions(),
    }


def file_records(paths: Iterable[str | Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for value in paths:
        path = Path(value).resolve()
        records.append({"path": str(path), "size": path.stat().st_size, "sha256": sha256_file(path)})
    return records


def finish_run(
    run: dict[str, Any],
    *,
    inputs: Iterable[str | Path],
    outputs: Iterable[str | Path],
    row_count: int,
    issues: list[DataIssue],
    elapsed_seconds: float,
) -> dict[str, Any]:
    run.update(
        {
            "finished_at": datetime.now(UTC).isoformat(),
            "elapsed_seconds": round(elapsed_seconds, 6),
            "row_count": int(row_count),
            "inputs": file_records(inputs),
            "outputs": file_records(outputs),
            "issues": {
                "total": len(issues),
                "by_code": {code: sum(1 for issue in issues if issue.code == code) for code in sorted({issue.code for issue in issues})},
                "sample": [issue.to_dict() for issue in issues[:100]],
            },
        }
    )
    return run


def write_json_atomic(path: str | Path, payload: dict[str, Any]) -> Path:
    output = Path(path)
    if output.exists():
        raise ToolkitError(f"输出文件已存在，拒绝覆盖: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix=f".{output.stem}.", suffix=output.suffix or ".json", dir=output.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, default=str)
            stream.write("\n")
        os.replace(name, output)
    except Exception as exc:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass
        if isinstance(exc, ToolkitError):
            raise
        raise ToolkitError(f"写入运行日志失败 {output}: {exc}") from exc
    return output
