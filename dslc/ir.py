"""
FlowQL Intermediate Representation (IR).

Linear intermediate representation of statements and pipeline stages.
Provides structured, inspectable steps for optimization passes, target code generators,
and the demo web UI.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from dslc.ast_nodes import (
    Program,
    Stmt,
    DatasetDecl,
    LetStmt,
    PipelineAssign,
    PrintStmt,
    Stage,
    FilterStage,
    SelectStage,
    GroupStage,
    SortStage,
    LimitStage,
    Expr,
    NumberLiteral,
    StringLiteral,
    BoolLiteral,
    Identifier,
    BinaryOp,
    UnaryOp,
)


def expr_to_str(expr: Expr) -> str:
    """Format an AST expression back to readable FlowQL syntax."""
    if isinstance(expr, NumberLiteral):
        return str(expr.value)
    elif isinstance(expr, StringLiteral):
        return f'"{expr.value}"'
    elif isinstance(expr, BoolLiteral):
        return "true" if expr.value else "false"
    elif isinstance(expr, Identifier):
        return expr.name
    elif isinstance(expr, UnaryOp):
        if expr.op == "not":
            return f"not {expr_to_str(expr.expr)}"
        return f"-{expr_to_str(expr.expr)}"
    elif isinstance(expr, BinaryOp):
        left_str = expr_to_str(expr.left)
        right_str = expr_to_str(expr.right)
        return f"({left_str} {expr.op} {right_str})"
    return ""


@dataclass
class IRStep:
    step_id: int
    op: str  # "load", "let", "filter", "select", "group", "sort", "limit", "print", "alias"
    input_ref: str
    output_ref: str
    details: Dict[str, Any] = field(default_factory=dict)
    comment: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert IR step to clean dictionary for UI and serialization."""
        clean_details = {}
        for k, v in self.details.items():
            if isinstance(v, Expr):
                clean_details[k] = expr_to_str(v)
            else:
                clean_details[k] = v
        return {
            "step_id": self.step_id,
            "op": self.op,
            "input": self.input_ref,
            "output": self.output_ref,
            "details": clean_details,
            "comment": self.comment
        }


class IRGenerator:
    """Lowers a validated Program AST into a linear sequence of IRSteps."""

    def __init__(self):
        self.step_counter = 1

    def lower(self, program: Program) -> List[IRStep]:
        steps: List[IRStep] = []
        if not program:
            return steps

        for stmt in program.statements:
            if isinstance(stmt, DatasetDecl):
                step = IRStep(
                    step_id=self.step_counter,
                    op="load",
                    input_ref=stmt.path,
                    output_ref=stmt.name,
                    details={
                        "path": stmt.path,
                        "schema": {c.name: c.col_type for c in stmt.columns}
                    },
                    comment=f"Load CSV dataset into '{stmt.name}'"
                )
                self.step_counter += 1
                steps.append(step)

            elif isinstance(stmt, LetStmt):
                step = IRStep(
                    step_id=self.step_counter,
                    op="let",
                    input_ref="",
                    output_ref=stmt.name,
                    details={
                        "expr": stmt.expr,
                        "expr_str": expr_to_str(stmt.expr)
                    },
                    comment=f"Define scalar variable '{stmt.name}'"
                )
                self.step_counter += 1
                steps.append(step)

            elif isinstance(stmt, PipelineAssign):
                if not stmt.stages:
                    # Direct alias
                    step = IRStep(
                        step_id=self.step_counter,
                        op="alias",
                        input_ref=stmt.source_table,
                        output_ref=stmt.target,
                        details={},
                        comment=f"Alias '{stmt.source_table}' as '{stmt.target}'"
                    )
                    self.step_counter += 1
                    steps.append(step)
                else:
                    curr_in = stmt.source_table
                    num_stages = len(stmt.stages)
                    for idx, stage in enumerate(stmt.stages):
                        is_last = (idx == num_stages - 1)
                        # Name intermediate tables or final target
                        stage_out = stmt.target if is_last else f"{stmt.target}_step{idx + 1}"

                        if isinstance(stage, FilterStage):
                            step = IRStep(
                                step_id=self.step_counter,
                                op="filter",
                                input_ref=curr_in,
                                output_ref=stage_out,
                                details={
                                    "predicate": stage.predicate,
                                    "predicate_str": expr_to_str(stage.predicate)
                                },
                                comment=f"Filter rows where {expr_to_str(stage.predicate)}"
                            )
                        elif isinstance(stage, SelectStage):
                            step = IRStep(
                                step_id=self.step_counter,
                                op="select",
                                input_ref=curr_in,
                                output_ref=stage_out,
                                details={"columns": list(stage.columns)},
                                comment=f"Select columns {', '.join(stage.columns)}"
                            )
                        elif isinstance(stage, GroupStage):
                            agg_func = stage.agg_func.lower()
                            res_col = f"{agg_func}_{stage.agg_col}"
                            step = IRStep(
                                step_id=self.step_counter,
                                op="group",
                                input_ref=curr_in,
                                output_ref=stage_out,
                                details={
                                    "key_col": stage.key_col,
                                    "agg_func": agg_func,
                                    "agg_col": stage.agg_col,
                                    "result_col": res_col
                                },
                                comment=f"Group by {stage.key_col}, calculate {agg_func}({stage.agg_col}) -> {res_col}"
                            )
                        elif isinstance(stage, SortStage):
                            direction = stage.direction.lower()
                            step = IRStep(
                                step_id=self.step_counter,
                                op="sort",
                                input_ref=curr_in,
                                output_ref=stage_out,
                                details={
                                    "column": stage.sort_col,
                                    "direction": direction
                                },
                                comment=f"Sort by {stage.sort_col} {direction.upper()}"
                            )
                        elif isinstance(stage, LimitStage):
                            step = IRStep(
                                step_id=self.step_counter,
                                op="limit",
                                input_ref=curr_in,
                                output_ref=stage_out,
                                details={"count": stage.count},
                                comment=f"Limit to first {stage.count} rows"
                            )
                        else:
                            continue

                        self.step_counter += 1
                        steps.append(step)
                        curr_in = stage_out

            elif isinstance(stmt, PrintStmt):
                step = IRStep(
                    step_id=self.step_counter,
                    op="print",
                    input_ref=stmt.table_name,
                    output_ref="",
                    details={"table": stmt.table_name},
                    comment=f"Print table '{stmt.table_name}'"
                )
                self.step_counter += 1
                steps.append(step)

        return steps
