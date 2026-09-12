from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InputSelection(StrictModel):
    file_id: str
    sheet: str | int = 0
    header_row: int = Field(default=1, ge=1, le=1048576)


class TaskSpec(StrictModel):
    inputs: list[InputSelection] = Field(default_factory=list, max_length=10)
    request: str = Field(default="", max_length=20000)
    rules: dict[str, Any] = Field(default_factory=dict)
    output_mode: Literal["new", "template"] = "new"


class Operation(StrictModel):
    kind: Literal["append", "join", "clean", "compare", "group", "melt", "pivot", "template", "recalculate"]
    inputs: list[InputSelection] = Field(min_length=1, max_length=10)
    params: dict[str, Any] = Field(default_factory=dict)


class OperationPlan(StrictModel):
    steps: list[Operation] = Field(min_length=1, max_length=30)
    questions: list[str] = Field(default_factory=list)


class TaskResult(StrictModel):
    status: Literal["pending", "running", "waiting", "succeeded", "failed", "cancelled"]
    outputs: list[dict[str, Any]] = Field(default_factory=list)
    statistics: dict[str, Any] = Field(default_factory=dict)
    issues: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None
