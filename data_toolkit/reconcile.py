from __future__ import annotations

from typing import Iterable

import pandas as pd

from .config import ToolConfig
from .models import CompareResult, MergeResult, ToolkitError


def _require_columns(frame: pd.DataFrame, columns: Iterable[str], label: str) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ToolkitError(f"{label}缺少关键列: {', '.join(missing)}")


def _key_tuples(frame: pd.DataFrame, keys: list[str]) -> pd.Series:
    return pd.Series(list(map(tuple, frame[keys].astype(object).to_numpy())), index=frame.index, dtype=object)


def merge_dataframes(frames: list[pd.DataFrame], config: ToolConfig) -> MergeResult:
    if not frames:
        raise ToolkitError("merge 至少需要一个输入文件")
    if config.merge.mode == "append":
        return MergeResult(pd.concat(frames, ignore_index=True, sort=False))
    if len(frames) != 2:
        raise ToolkitError("join 模式必须且只能提供两个输入文件")
    left, right = frames
    keys = config.merge.keys
    if not keys:
        raise ToolkitError("join 模式必须配置 merge.keys")
    _require_columns(left, keys, "左表")
    _require_columns(right, keys, "右表")
    left_dup = left.duplicated(keys, keep=False).any()
    right_dup = right.duplicated(keys, keep=False).any()
    validation = config.merge.validate
    if validation in {"one_to_one", "one_to_many"} and left_dup:
        raise ToolkitError(f"连接基数 {validation} 不符：左表连接键不唯一")
    if validation in {"one_to_one", "many_to_one"} and right_dup:
        raise ToolkitError(f"连接基数 {validation} 不符：右表连接键不唯一")
    left_keys = _key_tuples(left, keys)
    right_keys = _key_tuples(right, keys)
    unmatched_left = left.loc[~left_keys.isin(set(right_keys))].copy()
    unmatched_right = right.loc[~right_keys.isin(set(left_keys))].copy()
    try:
        data = left.merge(right, on=keys, how=config.merge.how, validate=validation, suffixes=("_左", "_右"))
    except pd.errors.MergeError as exc:
        raise ToolkitError(f"连接基数不符: {exc}") from exc
    return MergeResult(data, unmatched_left, unmatched_right)


def compare_dataframes(left: pd.DataFrame, right: pd.DataFrame, config: ToolConfig) -> CompareResult:
    keys = config.compare.keys
    if not keys:
        raise ToolkitError("compare 必须配置 compare.keys")
    _require_columns(left, keys, "左表")
    _require_columns(right, keys, "右表")
    if left.duplicated(keys, keep=False).any() or right.duplicated(keys, keep=False).any():
        raise ToolkitError("对账键存在重复主键")
    fields = config.compare.columns or [column for column in left.columns if column in right.columns and column not in keys]
    _require_columns(left, fields, "左表")
    _require_columns(right, fields, "右表")

    left_keys = _key_tuples(left, keys)
    right_keys = _key_tuples(right, keys)
    added = right.loc[~right_keys.isin(set(left_keys))].copy().reset_index(drop=True)
    removed = left.loc[~left_keys.isin(set(right_keys))].copy().reset_index(drop=True)
    left_indexed = left.set_index(keys)
    right_indexed = right.set_index(keys)
    common = left_indexed.index.intersection(right_indexed.index)
    changes: list[dict[str, object]] = []
    for key in common:
        left_row = left_indexed.loc[key]
        right_row = right_indexed.loc[key]
        key_values = key if isinstance(key, tuple) else (key,)
        key_data = dict(zip(keys, key_values, strict=True))
        for field in fields:
            left_value = left_row[field]
            right_value = right_row[field]
            left_missing = bool(pd.isna(left_value))
            right_missing = bool(pd.isna(right_value))
            equal = left_missing and right_missing
            if not left_missing and not right_missing:
                equal = bool(left_value == right_value)
            if not bool(equal):
                changes.append({**key_data, "字段": field, "左值": left_value, "右值": right_value})
    return CompareResult(added, removed, pd.DataFrame(changes, columns=[*keys, "字段", "左值", "右值"]))
