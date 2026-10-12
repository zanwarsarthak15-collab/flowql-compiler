"""
FlowQL Abstract Syntax Tree (AST) Nodes.

Dataclasses representing language constructs built by the parser.
Includes serialization to dictionary and readable tree formatting for demonstrations.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Union, Any


@dataclass
class ASTNode:
    line: int = 1
    column: int = 1

    def to_dict(self) -> dict:
        """Convert node to a JSON-serializable dictionary."""
        d = {"node_type": self.__class__.__name__}
        for k, v in self.__dict__.items():
            if isinstance(v, ASTNode):
                d[k] = v.to_dict()
            elif isinstance(v, list):
                d[k] = [item.to_dict() if isinstance(item, ASTNode) else item for item in v]
            else:
                d[k] = v
        return d

    def to_tree_str(self, indent: int = 0) -> str:
        """Render node as an indented human-readable tree string for viva demo."""
        prefix = "  " * indent
        details = []
        children = []
        for k, v in self.__dict__.items():
            if k in ("line", "column"):
                continue
            if isinstance(v, ASTNode):
                children.append((k, v))
            elif isinstance(v, list) and v and isinstance(v[0], ASTNode):
                for idx, item in enumerate(v):
                    children.append((f"{k}[{idx}]", item))
            else:
                details.append(f"{k}={repr(v)}")
        detail_str = f" ({', '.join(details)})" if details else ""
        lines = [f"{prefix}{self.__class__.__name__}{detail_str}"]
        for child_name, child in children:
            lines.append(f"{prefix}  {child_name}:")
            lines.append(child.to_tree_str(indent + 2))
        return "\n".join(lines)


# Column definition for dataset schema
@dataclass
class ColumnDef(ASTNode):
    name: str = ""
    col_type: str = ""  # 'num', 'str', 'bool'


# Expressions
@dataclass
class Expr(ASTNode):
    pass


@dataclass
class NumberLiteral(Expr):
    value: Union[int, float] = 0


@dataclass
class StringLiteral(Expr):
    value: str = ""


@dataclass
class BoolLiteral(Expr):
    value: bool = False


@dataclass
class Identifier(Expr):
    name: str = ""


@dataclass
class BinaryOp(Expr):
    op: str = ""  # '+', '-', '*', '/', '%', '==', '!=', '<', '<=', '>', '>=', 'and', 'or'
    left: Expr = field(default_factory=Expr)
    right: Expr = field(default_factory=Expr)


@dataclass
class UnaryOp(Expr):
    op: str = ""  # '-', 'not'
    expr: Expr = field(default_factory=Expr)


# Pipeline Stages
@dataclass
class Stage(ASTNode):
    pass


@dataclass
class FilterStage(Stage):
    predicate: Expr = field(default_factory=Expr)


@dataclass
class SelectStage(Stage):
    columns: List[str] = field(default_factory=list)


@dataclass
class GroupStage(Stage):
    key_col: str = ""
    agg_func: str = ""  # 'sum', 'avg', 'min', 'max', 'count'
    agg_col: str = ""


@dataclass
class SortStage(Stage):
    sort_col: str = ""
    direction: str = "asc"  # 'asc' or 'desc'


@dataclass
class LimitStage(Stage):
    count: int = 0


# Statements
@dataclass
class Stmt(ASTNode):
    pass


@dataclass
class DatasetDecl(Stmt):
    name: str = ""
    columns: List[ColumnDef] = field(default_factory=list)
    path: str = ""


@dataclass
class LetStmt(Stmt):
    name: str = ""
    expr: Expr = field(default_factory=Expr)


@dataclass
class PipelineAssign(Stmt):
    target: str = ""
    source_table: str = ""
    stages: List[Stage] = field(default_factory=list)


@dataclass
class PrintStmt(Stmt):
    table_name: str = ""


# Root Program Node
@dataclass
class Program(ASTNode):
    statements: List[Stmt] = field(default_factory=list)
