from typing import Literal
from pydantic import BaseModel


class Finding(BaseModel):
    file: str
    line: str
    severity: Literal["error", "warn", "info"]
    issue: str
    suggestion: str


class ReviewResult(BaseModel):
    findings: list[Finding]
