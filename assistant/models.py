from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InputSelection(StrictModel):
    file_id: str | None = None
    sheet: str | int = 0
    header_row: int = Field(default=1, ge=1, le=1048576)
    workbook_id: str | None = None
    version: int | None = Field(default=None, ge=1)
    sheet_id: str | None = None
    range: dict[str, int] | None = None

    @model_validator(mode='after')
    def input_kind(self):
        if bool(self.file_id) == bool(self.workbook_id):
            raise ValueError('须且只能指定文件或工作簿输入')
        if self.workbook_id and (self.version is None or not self.sheet_id):
            raise ValueError('工作簿输入须包含版本与工作表标识')
        if self.file_id and any(v is not None for v in (self.version, self.sheet_id, self.range)):
            raise ValueError('文件输入不能包含工作簿选区属性')
        if self.range:
            from .workbook_model import validate_range
            validate_range(self.range)
        return self


class TaskSpec(StrictModel):
    inputs: list[InputSelection] = Field(default_factory=list, max_length=10)
    request: str = Field(default="", max_length=20000)
    rules: dict[str, Any] = Field(default_factory=dict)
    output_mode: Literal["new", "template"] = "new"


class Operation(StrictModel):
    kind: Literal["append", "join", "clean", "compare", "group", "melt", "pivot", "template", "recalculate", "calculate", "classify", "create_table", "edit_workbook"]
    inputs: list[InputSelection] = Field(default_factory=list, max_length=10)
    params: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode='after')
    def input_count(self):
        if self.kind == 'create_table':
            if self.inputs:
                raise ValueError('建表不接收输入文件')
        elif not self.inputs:
            raise ValueError('此操作需要输入')
        if self.kind in {'calculate', 'classify', 'edit_workbook'} and len(self.inputs) != 1:
            raise ValueError('此操作需要一个明确输入')
        if self.kind == 'edit_workbook' and not self.inputs[0].workbook_id:
            raise ValueError('编辑须指定工作簿版本与工作表')
        if self.kind in {'template', 'recalculate'} and any(i.workbook_id for i in self.inputs):
            raise ValueError('模板和 Excel 原生重算使用文件输入，请先导出副本')
        return self


class OperationPlan(StrictModel):
    steps: list[Operation] = Field(min_length=1, max_length=30)
    questions: list[str] = Field(default_factory=list)


class TaskResult(StrictModel):
    status: Literal["pending", "running", "waiting", "succeeded", "failed", "cancelled"]
    outputs: list[dict[str, Any]] = Field(default_factory=list)
    statistics: dict[str, Any] = Field(default_factory=dict)
    issues: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None
