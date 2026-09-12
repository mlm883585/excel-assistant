from __future__ import annotations

from typing import Any

import pandas as pd


def _safe_extreme(series: pd.Series, method: str) -> Any:
    try:
        non_null = series.dropna()
        if non_null.empty:
            return None
        return getattr(non_null, method)()
    except (TypeError, ValueError):
        return None


def profile_dataframe(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    count = len(frame)
    for column in frame.columns:
        series = frame[column]
        null_count = int(series.isna().sum())
        rows.append(
            {
                "字段": str(column),
                "数据类型": str(series.dtype),
                "记录数": count,
                "空值数": null_count,
                "空值率%": round(null_count / count * 100, 4) if count else 0,
                "唯一值数": int(series.nunique(dropna=True)),
                "重复值数": int(series.duplicated(keep=False).sum()),
                "最小值": _safe_extreme(series, "min"),
                "最大值": _safe_extreme(series, "max"),
            }
        )
    return pd.DataFrame(rows)
