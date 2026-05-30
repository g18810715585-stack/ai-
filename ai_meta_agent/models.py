from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class SourceKind(str, Enum):
    LOCAL_EXCEL = "local_excel"
    FEISHU = "feishu"


class PlanningSource(BaseModel):
    id: str
    kind: SourceKind
    path: str | None = None
    url: str | None = None
    role: str = "planning"

    @model_validator(mode="after")
    def validate_location(self) -> "PlanningSource":
        if self.kind == SourceKind.LOCAL_EXCEL and not self.path:
            raise ValueError("local_excel source requires path")
        if self.kind == SourceKind.FEISHU and not self.url:
            raise ValueError("feishu source requires url")
        return self


class ConfigTableRef(BaseModel):
    path: str
    sheet: str | None = None


class ConfigRoot(BaseModel):
    path: str
    recursive: bool = True


class AiSettings(BaseModel):
    provider: str = "baseai"
    api_key_env: str = "BASEAI_API_KEY"
    base_url_env: str = "BASEAI_BASE_URL"
    model_env: str = "BASEAI_MODEL"
    default_base_url: str = "https://baseai.rivergame.net/v1"
    default_model: str = "gpt-5.5"


class Manifest(BaseModel):
    project: str
    mode: Literal["readonly", "draft", "supervised_write", "auto_overwrite"] = "supervised_write"
    schema_path: str
    run_root: str = ".runs"
    planning_sources: list[PlanningSource]
    config_tables: dict[str, ConfigTableRef] = Field(default_factory=dict)
    config_roots: list[ConfigRoot] = Field(default_factory=list)
    target_tables: list[str] = Field(default_factory=list)
    habit_store: str = ".knowledge/habits.jsonl"
    ai: AiSettings = Field(default_factory=AiSettings)


class FieldSpec(BaseModel):
    type: Literal["str", "int", "float", "bool", "date", "datetime", "any"] = "any"
    required: bool = False
    default: Any = None


class TableSchema(BaseModel):
    sheet: str | None = None
    primary_key: list[str] = Field(default_factory=list)
    group_key: str | None = None
    overwrite_strategy: Literal["field_level", "row_replace", "group_replace"] = "field_level"
    ai_write_permission: Literal["readonly", "draft", "supervised_write", "auto_write"] = "supervised_write"
    allow_update_fields: list[str] = Field(default_factory=list)
    preserve_fields: list[str] = Field(default_factory=list)
    block_update_fields: list[str] = Field(default_factory=list)
    fields: dict[str, FieldSpec] = Field(default_factory=dict)
    field_aliases: dict[str, str] = Field(default_factory=dict)


class RiskSettings(BaseModel):
    auto_apply_confidence: float = 0.9
    needs_review_confidence: float = 0.7
    large_delete_threshold: int = 20
    large_update_threshold: int = 50


class SchemaBundle(BaseModel):
    version: int = 1
    tables: dict[str, TableSchema]
    risk: RiskSettings = Field(default_factory=RiskSettings)


class SourceRef(BaseModel):
    workbook: str | None = None
    sheet: str | None = None
    row: int | None = None
    column: int | None = None
    field: str | None = None
    habit_id: str | None = None


class PatchOperation(BaseModel):
    op: Literal["insert", "update", "delete_where", "replace_group"]
    target_table: str
    match: dict[str, Any] = Field(default_factory=dict)
    set: dict[str, Any] = Field(default_factory=dict)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    source_ref: SourceRef = Field(default_factory=SourceRef)
    reason: str
    confidence: float = Field(ge=0, le=1)
    risk_level: Literal["low", "medium", "high"] = "medium"
    needs_confirmation: bool = True

    @model_validator(mode="after")
    def validate_payload(self) -> "PatchOperation":
        if self.op == "update" and (not self.match or not self.set):
            raise ValueError("update requires match and set")
        if self.op == "insert" and not self.rows:
            raise ValueError("insert requires rows")
        if self.op in {"delete_where", "replace_group"} and not self.match:
            raise ValueError(f"{self.op} requires match")
        return self


class Patch(BaseModel):
    patch_id: str
    project: str
    mode: str = "supervised_write"
    operations: list[PatchOperation]
    generated_by: str = "ai-meta-agent"


class Habit(BaseModel):
    habit_id: str
    name: str
    scenario: str
    applies_to: dict[str, Any] = Field(default_factory=dict)
    action: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=0.7, ge=0, le=1)
    evidence: list[str] = Field(default_factory=list)
    last_used_at: str | None = None


class ValidationIssue(BaseModel):
    level: Literal["error", "warning", "needs_confirmation"]
    table: str | None = None
    row: int | None = None
    field: str | None = None
    message: str


class ValidationReport(BaseModel):
    errors: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[ValidationIssue] = Field(default_factory=list)
    needs_confirmation: list[ValidationIssue] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


class CellIR(BaseModel):
    row: int
    column: int
    address: str
    value: Any = None
    is_merged: bool = False
    merged_range: str | None = None
    is_hidden_row: bool = False
    is_hidden_column: bool = False
    fill: str | None = None
    comment: str | None = None


class SheetIR(BaseModel):
    name: str
    max_row: int
    max_column: int
    hidden_rows: list[int] = Field(default_factory=list)
    hidden_columns: list[str] = Field(default_factory=list)
    merged_ranges: list[str] = Field(default_factory=list)
    headers: list[str] = Field(default_factory=list)
    header_row: int | None = None
    sample_rows: list[dict[str, Any]] = Field(default_factory=list)
    cells: list[CellIR] = Field(default_factory=list)


class WorkbookIR(BaseModel):
    source_id: str
    source_type: SourceKind
    path: str | None = None
    url: str | None = None
    sheets: list[SheetIR]


def resolve_path(base_dir: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()
