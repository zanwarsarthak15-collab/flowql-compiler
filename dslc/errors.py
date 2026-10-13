"""
FlowQL Compiler Error System.

Defines standardized error codes and the CompileError data structure used
across lexical, syntax, and semantic analysis phases.
"""
from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class CompileError:
    code: str
    message: str
    line: int
    column: int
    source_line: Optional[str] = None

    def to_dict(self):
        return {
            "code": self.code,
            "message": self.message,
            "line": self.line,
            "column": self.column,
            "source_line": self.source_line or ""
        }

    def __str__(self):
        loc = f"Line {self.line}, Col {self.column}"
        return f"[{self.code}] {loc}: {self.message}"


# Predefined Error Codes
E001_ILLEGAL_CHAR = "E001"
E002_UNTERMINATED_STRING = "E002"
E010_UNEXPECTED_TOKEN = "E010"
E011_UNEXPECTED_EOF = "E011"

E101_UNDEFINED_NAME = "E101"
E102_REDECLARATION = "E102"
E103_UNKNOWN_COLUMN = "E103"
E104_TYPE_MISMATCH = "E104"
E105_NON_BOOL_FILTER = "E105"
E106_NON_NUMERIC_AGG = "E106"
E107_INVALID_LIMIT = "E107"
E108_INVALID_PRINT = "E108"
E109_CSV_SCHEMA_MISMATCH = "E109"
