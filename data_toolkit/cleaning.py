from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

import pandas as pd
from rapidfuzz import fuzz
from rapidfuzz.distance import Levenshtein

from .config import ColumnRule, ToolConfig
from .models import CleanResult, DataIssue, HeaderSuggestion, ToolkitError
from .validation import validate_structure


def _header_key(value: Any) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value))).casefold()


def _is_null(value: Any, null_values: set[str]) -> bool:
    if value is None or value is pd.NA:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return isinstance(value, str) and value.strip() in null_values


def _clean_string(value: Any, rule: ColumnRule) -> str:
    text = str(value)
    if rule.unicode_nfkc:
        text = unicodedata.normalize("NFKC", text)
    if rule.trim:
        text = text.strip()
    return str(rule.replacements.get(text, text))


def _convert(value: Any, rule: ColumnRule, null_values: set[str]) -> Any:
    if _is_null(value, null_values):
        return None
    if rule.type == "string":
        return _clean_string(value, rule)
    text = _clean_string(value, rule)
    replacement = rule.replacements.get(text, text)
    if rule.type == "decimal":
        return Decimal(str(replacement).replace(",", ""))
    if rule.type == "integer":
        number = Decimal(str(replacement).replace(",", ""))
        if number != number.to_integral_value():
            raise ValueError("不是整数")
        return int(number)
    if rule.type == "float":
        return float(str(replacement).replace(",", ""))
    if rule.type == "boolean":
        normalized = str(replacement).strip().casefold()
        if normalized in {"true", "1", "是", "y", "yes"}:
            return True
        if normalized in {"false", "0", "否", "n", "no"}:
            return False
        raise ValueError("不是布尔值")
    parsed = pd.to_datetime(replacement, errors="raise")
    if rule.type == "date":
        return parsed.date() if hasattr(parsed, "date") else date.fromisoformat(str(parsed))
    if rule.type == "datetime":
        return parsed.to_pydatetime() if hasattr(parsed, "to_pydatetime") else datetime.fromisoformat(str(parsed))
    raise ValueError(f"不支持的类型 {rule.type}")


def _resolved_columns(frame: pd.DataFrame, config: ToolConfig) -> dict[Any, str]:
    lookup: dict[str, str] = {}
    for canonical, rule in config.columns.items():
        for alias in [canonical, *rule.aliases]:
            key = _header_key(alias)
            existing = lookup.get(key)
            if existing and existing != canonical:
                raise ToolkitError(f"字段别名冲突: {alias}")
            lookup[key] = canonical
    resolved: dict[Any, str] = {}
    seen_targets: set[str] = set()
    for source in frame.columns:
        target = lookup.get(_header_key(source))
        if target:
            if target in seen_targets:
                raise ToolkitError(f"多个输入字段同时映射到 {target}")
            resolved[source] = target
            seen_targets.add(target)
    missing = [name for name, rule in config.columns.items() if rule.required and name not in seen_targets]
    if missing:
        raise ToolkitError(f"缺少关键列: {', '.join(missing)}")
    return resolved


def suggest_header_mappings(headers: Iterable[str], config: ToolConfig, threshold: int = 90) -> list[HeaderSuggestion]:
    targets = list(config.columns)
    exact = {_header_key(item) for target, rule in config.columns.items() for item in [target, *rule.aliases]}
    suggestions: list[HeaderSuggestion] = []
    for header in headers:
        if _header_key(header) in exact or not targets:
            continue
        source = str(header)
        scored: list[tuple[float, str]] = []
        for target in targets:
            # Header names are often only 3-6 Chinese characters. A single OCR or
            # typing error should still be a useful suggestion, while never being
            # applied automatically. The ten-character floor keeps that one edit
            # at 90 and RapidFuzz supplies the edit distance implementation.
            edit_score = 100.0 * (1.0 - Levenshtein.distance(source, target) / max(10, len(source), len(target)))
            scored.append((max(float(fuzz.WRatio(source, target)), edit_score), target))
        score, target = max(scored)
        if score >= threshold:
            suggestions.append(HeaderSuggestion(source, target, score))
    return suggestions


def clean_dataframe(frame: pd.DataFrame, config: ToolConfig, source_name: str | None = None) -> CleanResult:
    data = frame.copy()
    mapping = _resolved_columns(data, config)
    data = data.rename(columns=mapping)
    validate_structure(data, config)
    issues: list[DataIssue] = []
    null_values = {str(value).strip() for value in config.input.null_values}

    for name, rule in config.columns.items():
        if name not in data.columns:
            continue
        converted: list[Any] = []
        for position, value in enumerate(data[name].tolist(), start=(int(config.input.header_row) + 1 if config.input.header_row != "auto" else 2)):
            try:
                output = _convert(value, rule, null_values)
            except (ValueError, TypeError, InvalidOperation, OverflowError) as exc:
                output = None
                issues.append(DataIssue("错误", "invalid_type", f"无法转换为 {rule.type}: {exc}", position, name, value, source_name))
            if output is None and rule.required:
                issues.append(DataIssue("错误", "required", "必填字段为空", position, name, value, source_name))
            if output is not None:
                try:
                    if rule.min is not None and output < rule.min:
                        issues.append(DataIssue("错误", "min_value", f"值小于最小值 {rule.min}", position, name, value, source_name))
                    if rule.max is not None and output > rule.max:
                        issues.append(DataIssue("错误", "max_value", f"值大于最大值 {rule.max}", position, name, value, source_name))
                except TypeError:
                    pass
                if rule.allowed_values is not None and output not in rule.allowed_values:
                    issues.append(DataIssue("错误", "allowed_value", "值不在允许值列表中", position, name, value, source_name))
                if rule.regex and not re.fullmatch(rule.regex, str(output)):
                    issues.append(DataIssue("错误", "regex", "值不符合正则表达式", position, name, value, source_name))
            converted.append(output)
        data[name] = pd.Series(converted, index=data.index, dtype=object)

    unique_groups: list[list[str]] = []
    if config.duplicates.keys:
        unique_groups.append(list(config.duplicates.keys))
    for name, rule in config.columns.items():
        if rule.unique and [name] not in unique_groups:
            unique_groups.append([name])
    for unique_keys in unique_groups:
        missing_keys = [key for key in unique_keys if key not in data.columns]
        if missing_keys:
            raise ToolkitError(f"去重关键列不存在: {', '.join(missing_keys)}")
        duplicate_mask = data.duplicated(subset=unique_keys, keep=False)
        for position, is_duplicate in enumerate(duplicate_mask.tolist(), start=(int(config.input.header_row) + 1 if config.input.header_row != "auto" else 2)):
            if is_duplicate:
                issues.append(DataIssue("错误", "duplicate_key", f"重复键: {', '.join(unique_keys)}", position, ",".join(unique_keys), None, source_name))
        if duplicate_mask.any() and config.duplicates.policy == "error":
            raise ToolkitError("检测到重复主键，duplicates.policy=error")
        if config.duplicates.policy in {"keep_first", "keep_last"}:
            keep = "first" if config.duplicates.policy == "keep_first" else "last"
            data = data.drop_duplicates(subset=unique_keys, keep=keep).reset_index(drop=True)

    output_renames = {name: rule.rename for name, rule in config.columns.items() if rule.rename and name in data.columns}
    for source, target in output_renames.items():
        if target != source and target in data.columns and target not in output_renames:
            raise ToolkitError(f"字段重命名冲突: {source} -> {target}")
    if len(set(output_renames.values())) != len(output_renames):
        raise ToolkitError("多个字段不能重命名为同一个输出字段")
    data = data.rename(columns=output_renames)

    order = [column for column in config.output.column_order if column in data.columns]
    if order:
        data = data[[*order, *[column for column in data.columns if column not in order]]]
    return CleanResult(data=data, issues=issues, suggestions=suggest_header_mappings(frame.columns.astype(str), config))
