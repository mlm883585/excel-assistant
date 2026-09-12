from __future__ import annotations

import pandas as pd

from .config import ToolConfig
from .models import ToolkitError


def validate_structure(frame: pd.DataFrame, config: ToolConfig) -> None:
    """Use Pandera as the structural validation boundary after aliases resolve."""
    try:
        import pandera.pandas as pa
    except ImportError as exc:
        raise ToolkitError("通用数据工具需要 analytics 依赖档中的 Pandera") from exc

    schema = pa.DataFrameSchema(
        {
            name: pa.Column(None, required=rule.required, nullable=True)
            for name, rule in config.columns.items()
        },
        strict=False,
        coerce=False,
    )
    try:
        schema.validate(frame, lazy=True)
    except pa.errors.SchemaErrors as exc:
        raise ToolkitError(f"数据结构校验失败: {exc.failure_cases.to_dict(orient='records')}") from exc
