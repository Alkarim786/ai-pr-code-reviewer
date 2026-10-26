"""Structured review output. Everything an agent says must validate against these."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Severity(str, Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"
    info = "info"


class Category(str, Enum):
    bug = "bug"
    security = "security"
    performance = "performance"
    style = "style"


SEVERITY_RANK = {
    Severity.critical: 5,
    Severity.high: 4,
    Severity.medium: 3,
    Severity.low: 2,
    Severity.info: 1,
}


class Finding(BaseModel):
    file: str = Field(min_length=1)
    line: int = Field(ge=1)
    severity: Severity
    category: Category
    message: str = Field(min_length=1, max_length=2000)
    suggestion: str | None = Field(default=None, max_length=2000)
    source: str = "llm"  # "llm", "static" or "static+llm" after dedup
    agent: str | None = None
    rule: str | None = None  # static rule id, e.g. "B608"


class ReviewResult(BaseModel):
    findings: list[Finding] = []
    dropped_out_of_diff: int = 0
    dropped_invalid: int = 0
    dropped_over_cap: int = 0
    merged_duplicates: int = 0
    agent_errors: list[str] = []
    input_tokens: int = 0
    output_tokens: int = 0
