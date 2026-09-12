from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd


class ToolkitError(RuntimeError):
    """A structural or processing error that must stop the command."""


@dataclass(slots=True)
class DataIssue:
    severity: str
    code: str
    message: str
    row: int | None = None
    column: str | None = None
    value: Any = None
    source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "严重级别": self.severity,
            "问题代码": self.code,
            "消息": self.message,
            "源文件": self.source,
            "行号": self.row,
            "字段": self.column,
            "原值": self.value,
        }


@dataclass(slots=True)
class HeaderSuggestion:
    source: str
    target: str
    score: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CleanResult:
    data: pd.DataFrame
    issues: list[DataIssue] = field(default_factory=list)
    suggestions: list[HeaderSuggestion] = field(default_factory=list)


@dataclass(slots=True)
class MergeResult:
    data: pd.DataFrame
    unmatched_left: pd.DataFrame = field(default_factory=pd.DataFrame)
    unmatched_right: pd.DataFrame = field(default_factory=pd.DataFrame)


@dataclass(slots=True)
class CompareResult:
    added: pd.DataFrame
    removed: pd.DataFrame
    changed: pd.DataFrame
