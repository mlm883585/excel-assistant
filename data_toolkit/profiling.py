from __future__ import annotations

from typing import Any

import pandas as pd


def _null_mask(series: pd.Series) -> pd.Series:
    """Treat NaN and empty/whitespace strings as missing (read() normalizes nulls to '')."""
    mask = series.isna()
    if series.dtype == object:
        mask = mask | series.map(lambda v: isinstance(v, str) and not v.strip())
    return mask


def _safe_extreme(series: pd.Series, method: str) -> Any:
    try:
        non_null = series[~_null_mask(series)]
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
        null_count = int(_null_mask(series).sum())
        rows.append(
            {
                "字段": str(column),
                "数据类型": str(series.dtype),
                "记录数": count,
                "空值数": null_count,
                "空值率%": round(null_count / count * 100, 4) if count else 0,
                "唯一值数": int(series[~_null_mask(series)].nunique()),
                "重复值数": int(series.duplicated(keep=False).sum()),
                "最小值": _safe_extreme(series, "min"),
                "最大值": _safe_extreme(series, "max"),
            }
        )
    return pd.DataFrame(rows)


def _native(value: Any) -> Any:
    if value is None:
        return None
    import numpy as np
    if isinstance(value, np.generic):
        return _native(value.item())
    if isinstance(value, (pd.Timestamp, pd.Timedelta)):
        return value.isoformat()
    if isinstance(value, (bool, int, float, str)):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _sample_values(series: pd.Series, top_n: int) -> list[Any]:
    try:
        non_null = series[~_null_mask(series)]
        if non_null.empty:
            return []
        counts = non_null.value_counts(sort=True, dropna=True)
        return [_native(value) for value in counts.index[:top_n]]
    except (TypeError, ValueError):
        return []


def profile_columns(frame: pd.DataFrame, sample_limit: int = 5) -> list[dict[str, Any]]:
    """Compact per-column profile for agent context (not a human report)."""
    columns: list[dict[str, Any]] = []
    count = len(frame)
    for column in frame.columns:
        series = frame[column]
        null_count = int(_null_mask(series).sum())
        columns.append(
            {
                "name": str(column),
                "dtype": str(series.dtype),
                "null_rate": round(null_count / count, 4) if count else 0.0,
                "unique": int(series[~_null_mask(series)].nunique()),
                "samples": _sample_values(series, sample_limit),
                "min": _native(_safe_extreme(series, "min")),
                "max": _native(_safe_extreme(series, "max")),
            }
        )
    return columns
