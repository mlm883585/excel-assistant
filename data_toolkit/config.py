from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import ToolkitError


SUPPORTED_TYPES = {"string", "integer", "decimal", "float", "boolean", "date", "datetime"}


@dataclass(slots=True)
class InputConfig:
    sheet: str | None = None
    header_row: int | str = "auto"
    null_values: list[str] = field(default_factory=lambda: [""])
    id_columns: list[str] = field(default_factory=list)
    encoding: str = "utf-8-sig"


@dataclass(slots=True)
class ColumnRule:
    name: str
    aliases: list[str] = field(default_factory=list)
    rename: str | None = None
    type: str = "string"
    required: bool = False
    unique: bool = False
    min: float | int | None = None
    max: float | int | None = None
    regex: str | None = None
    allowed_values: list[Any] | None = None
    trim: bool = True
    unicode_nfkc: bool = True
    replacements: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DuplicateConfig:
    keys: list[str] = field(default_factory=list)
    policy: str = "report"


@dataclass(slots=True)
class MergeConfig:
    mode: str = "append"
    keys: list[str] = field(default_factory=list)
    how: str = "outer"
    validate: str = "many_to_many"


@dataclass(slots=True)
class CompareConfig:
    keys: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)


@dataclass(slots=True)
class OutputConfig:
    column_order: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ToolConfig:
    schema_version: int
    input: InputConfig
    columns: dict[str, ColumnRule]
    duplicates: DuplicateConfig
    merge: MergeConfig
    compare: CompareConfig
    output: OutputConfig


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ToolkitError(f"配置项 {label} 必须是 JSON 对象")
    return value


def _string_list(value: Any, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ToolkitError(f"配置项 {label} 必须是字符串数组")
    return value


def _reject_unknown(value: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ToolkitError(f"{label} 包含未知配置项: {', '.join(unknown)}")


def parse_config(raw: dict[str, Any]) -> ToolConfig:
    if not isinstance(raw, dict):
        raise ToolkitError("配置根节点必须是 JSON 对象")
    if raw.get("schema_version") != 1:
        raise ToolkitError("仅支持 schema_version: 1")
    _reject_unknown(raw, {"$schema", "schema_version", "input", "columns", "duplicates", "merge", "compare", "output"}, "配置根节点")

    input_raw = _mapping(raw.get("input"), "input")
    _reject_unknown(input_raw, {"sheet", "header_row", "null_values", "id_columns", "encoding"}, "input")
    header_row = input_raw.get("header_row", "auto")
    if header_row != "auto" and (not isinstance(header_row, int) or header_row < 1):
        raise ToolkitError("input.header_row 必须为 auto 或大于等于 1 的整数")
    if input_raw.get("sheet") is not None and not isinstance(input_raw.get("sheet"), str):
        raise ToolkitError("input.sheet 必须是字符串或 null")
    input_config = InputConfig(
        sheet=input_raw.get("sheet"),
        header_row=header_row,
        null_values=_string_list(input_raw.get("null_values", [""]), "input.null_values"),
        id_columns=_string_list(input_raw.get("id_columns", []), "input.id_columns"),
        encoding=str(input_raw.get("encoding", "utf-8-sig")),
    )

    columns_raw = _mapping(raw.get("columns"), "columns")
    columns: dict[str, ColumnRule] = {}
    for name, value in columns_raw.items():
        if not isinstance(name, str) or not name:
            raise ToolkitError("columns 中的字段名称不能为空")
        rule_raw = _mapping(value, f"columns.{name}")
        _reject_unknown(
            rule_raw,
            {"aliases", "rename", "type", "required", "unique", "min", "max", "regex", "allowed_values", "trim", "unicode_nfkc", "replacements"},
            f"columns.{name}",
        )
        kind = str(rule_raw.get("type", "string")).lower()
        if kind not in SUPPORTED_TYPES:
            raise ToolkitError(f"字段 {name} 的 type 不受支持: {kind}")
        allowed = rule_raw.get("allowed_values")
        if allowed is not None and not isinstance(allowed, list):
            raise ToolkitError(f"字段 {name} 的 allowed_values 必须是数组")
        replacements = _mapping(rule_raw.get("replacements"), f"columns.{name}.replacements")
        rename = rule_raw.get("rename")
        if rename is not None and (not isinstance(rename, str) or not rename):
            raise ToolkitError(f"字段 {name} 的 rename 必须是非空字符串或 null")
        regex = rule_raw.get("regex")
        if regex is not None:
            if not isinstance(regex, str):
                raise ToolkitError(f"字段 {name} 的 regex 必须是字符串或 null")
            try:
                re.compile(regex)
            except re.error as exc:
                raise ToolkitError(f"字段 {name} 的 regex 无效: {exc}") from exc
        columns[name] = ColumnRule(
            name=name,
            aliases=_string_list(rule_raw.get("aliases", []), f"columns.{name}.aliases"),
            rename=rename,
            type=kind,
            required=bool(rule_raw.get("required", False)),
            unique=bool(rule_raw.get("unique", False)),
            min=rule_raw.get("min"),
            max=rule_raw.get("max"),
            regex=regex,
            allowed_values=allowed,
            trim=bool(rule_raw.get("trim", True)),
            unicode_nfkc=bool(rule_raw.get("unicode_nfkc", True)),
            replacements={str(key): val for key, val in replacements.items()},
        )

    duplicates_raw = _mapping(raw.get("duplicates"), "duplicates")
    _reject_unknown(duplicates_raw, {"keys", "policy"}, "duplicates")
    policy = str(duplicates_raw.get("policy", "report"))
    if policy not in {"report", "keep_first", "keep_last", "error"}:
        raise ToolkitError("duplicates.policy 必须为 report/keep_first/keep_last/error")
    duplicates = DuplicateConfig(
        keys=_string_list(duplicates_raw.get("keys", []), "duplicates.keys"),
        policy=policy,
    )

    merge_raw = _mapping(raw.get("merge"), "merge")
    _reject_unknown(merge_raw, {"mode", "keys", "how", "validate"}, "merge")
    mode = str(merge_raw.get("mode", "append"))
    if mode not in {"append", "join"}:
        raise ToolkitError("merge.mode 必须为 append 或 join")
    how = str(merge_raw.get("how", "outer"))
    if how not in {"left", "right", "inner", "outer"}:
        raise ToolkitError("merge.how 必须为 left/right/inner/outer")
    validate = str(merge_raw.get("validate", "many_to_many"))
    if validate not in {"one_to_one", "one_to_many", "many_to_one", "many_to_many"}:
        raise ToolkitError("merge.validate 配置无效")
    merge = MergeConfig(mode=mode, keys=_string_list(merge_raw.get("keys", []), "merge.keys"), how=how, validate=validate)

    compare_raw = _mapping(raw.get("compare"), "compare")
    _reject_unknown(compare_raw, {"keys", "columns"}, "compare")
    compare = CompareConfig(
        keys=_string_list(compare_raw.get("keys", []), "compare.keys"),
        columns=_string_list(compare_raw.get("columns", []), "compare.columns"),
    )
    output_raw = _mapping(raw.get("output"), "output")
    _reject_unknown(output_raw, {"column_order"}, "output")
    output = OutputConfig(column_order=_string_list(output_raw.get("column_order", []), "output.column_order"))
    return ToolConfig(1, input_config, columns, duplicates, merge, compare, output)


def load_config(path: str | Path) -> ToolConfig:
    config_path = Path(path)
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ToolkitError(f"无法读取配置文件 {config_path}: {exc}") from exc
    return parse_config(raw)
