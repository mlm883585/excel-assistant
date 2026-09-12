from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from .models import ToolkitError


MAX_DATA_ROWS = 1_048_575


def issues_frame(issues: list[Any]) -> pd.DataFrame:
    rows = [issue.to_dict() if hasattr(issue, "to_dict") else dict(issue) for issue in issues]
    return pd.DataFrame(rows, columns=["严重级别", "问题代码", "消息", "源文件", "行号", "字段", "原值"])


def write_report(
    path: str | Path,
    *,
    summary: Mapping[str, Any],
    field_profile: pd.DataFrame | None = None,
    issues: pd.DataFrame | None = None,
    extras: Mapping[str, pd.DataFrame] | None = None,
) -> Path:
    output = Path(path)
    if output.exists():
        raise ToolkitError(f"输出文件已存在，拒绝覆盖: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix=f".{output.stem}.", suffix=".xlsx", dir=output.parent)
    os.close(handle)
    temp = Path(name)
    temp.unlink()
    profile = field_profile if field_profile is not None else pd.DataFrame(columns=["字段"])
    issue_data = issues if issues is not None else pd.DataFrame(columns=["严重级别", "问题代码", "消息"])
    try:
        with pd.ExcelWriter(temp, engine="xlsxwriter", engine_kwargs={"options": {"strings_to_formulas": False, "strings_to_urls": False}}) as writer:
            pd.DataFrame({"项目": list(summary), "值": list(summary.values())}).to_excel(writer, index=False, sheet_name="汇总")
            profile.to_excel(writer, index=False, sheet_name="字段概况")
            issue_data.to_excel(writer, index=False, sheet_name="问题明细")
            for sheet_name, frame in (extras or {}).items():
                if frame.empty:
                    frame.to_excel(writer, index=False, sheet_name=sheet_name[:31])
                    continue
                for number, start in enumerate(range(0, len(frame), MAX_DATA_ROWS), start=1):
                    name_part = sheet_name[:31] if len(frame) <= MAX_DATA_ROWS else f"{sheet_name[:27]}_{number:03d}"
                    frame.iloc[start : start + MAX_DATA_ROWS].to_excel(writer, index=False, sheet_name=name_part)
            header = writer.book.add_format({"bold": True, "bg_color": "#1F4E78", "font_color": "#FFFFFF", "border": 1})
            for worksheet in writer.sheets.values():
                worksheet.freeze_panes(1, 0)
                max_row = worksheet.dim_rowmax if worksheet.dim_rowmax is not None else 0
                max_column = worksheet.dim_colmax
                if max_column is not None and max_column >= 0:
                    worksheet.autofilter(0, 0, max(max_row, 1), max_column)
                    for column in range(max_column + 1):
                        worksheet.set_column(column, column, 18)
                        value = worksheet.table.get((0, column))
                        if value:
                            worksheet.write(0, column, value.string, header)
        os.replace(temp, output)
        return output
    except Exception as exc:
        temp.unlink(missing_ok=True)
        if isinstance(exc, ToolkitError):
            raise
        raise ToolkitError(f"写入报告失败 {output}: {exc}") from exc
