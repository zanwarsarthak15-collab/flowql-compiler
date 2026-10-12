"""
FlowQL Optimizer.

Implements two deterministic, lightweight optimization passes:
1. Constant Folding: Evaluates constant sub-expressions at compile time (e.g. 2 * 50 -> 100).
2. Filter Merging: Combines consecutive filter stages into a single stage with a logical 'and'.
"""
from typing import List, Tuple
from dslc.ast_nodes import (
    Expr,
    NumberLiteral,
    StringLiteral,
    BoolLiteral,
    BinaryOp,
    UnaryOp,
    Identifier,
)
from dslc.ir import IRStep, expr_to_str


def fold_constants(expr: Expr) -> Expr:
    """
    Recursively evaluate operations whose operands are known literals.
    """
    if isinstance(expr, UnaryOp):
        sub = fold_constants(expr.expr)
        if expr.op == "-" and isinstance(sub, NumberLiteral):
            return NumberLiteral(value=-sub.value, line=expr.line, column=expr.column)
        elif expr.op == "not" and isinstance(sub, BoolLiteral):
            return BoolLiteral(value=not sub.value, line=expr.line, column=expr.column)
        return UnaryOp(op=expr.op, expr=sub, line=expr.line, column=expr.column)

    elif isinstance(expr, BinaryOp):
        left = fold_constants(expr.left)
        right = fold_constants(expr.right)
        op = expr.op

        # Both numeric
        if isinstance(left, NumberLiteral) and isinstance(right, NumberLiteral):
            if op == "+":
                return NumberLiteral(value=left.value + right.value, line=expr.line, column=expr.column)
            elif op == "-":
                return NumberLiteral(value=left.value - right.value, line=expr.line, column=expr.column)
            elif op == "*":
                return NumberLiteral(value=left.value * right.value, line=expr.line, column=expr.column)
            elif op == "/":
                if right.value != 0:
                    val = left.value / right.value
                    if val.is_integer():
                        val = int(val)
                    return NumberLiteral(value=val, line=expr.line, column=expr.column)
            elif op == "%":
                if right.value != 0:
                    return NumberLiteral(value=left.value % right.value, line=expr.line, column=expr.column)
            elif op == "==":
                return BoolLiteral(value=left.value == right.value, line=expr.line, column=expr.column)
            elif op == "!=":
                return BoolLiteral(value=left.value != right.value, line=expr.line, column=expr.column)
            elif op == "<":
                return BoolLiteral(value=left.value < right.value, line=expr.line, column=expr.column)
            elif op == "<=":
                return BoolLiteral(value=left.value <= right.value, line=expr.line, column=expr.column)
            elif op == ">":
                return BoolLiteral(value=left.value > right.value, line=expr.line, column=expr.column)
            elif op == ">=":
                return BoolLiteral(value=left.value >= right.value, line=expr.line, column=expr.column)

        # Both string
        elif isinstance(left, StringLiteral) and isinstance(right, StringLiteral):
            if op == "+":
                return StringLiteral(value=left.value + right.value, line=expr.line, column=expr.column)
            elif op == "==":
                return BoolLiteral(value=left.value == right.value, line=expr.line, column=expr.column)
            elif op == "!=":
                return BoolLiteral(value=left.value != right.value, line=expr.line, column=expr.column)

        # Both boolean
        elif isinstance(left, BoolLiteral) and isinstance(right, BoolLiteral):
            if op == "and":
                return BoolLiteral(value=left.value and right.value, line=expr.line, column=expr.column)
            elif op == "or":
                return BoolLiteral(value=left.value or right.value, line=expr.line, column=expr.column)
            elif op == "==":
                return BoolLiteral(value=left.value == right.value, line=expr.line, column=expr.column)
            elif op == "!=":
                return BoolLiteral(value=left.value != right.value, line=expr.line, column=expr.column)

        return BinaryOp(op=op, left=left, right=right, line=expr.line, column=expr.column)

    return expr


def optimize_ir(steps: List[IRStep]) -> Tuple[List[IRStep], List[str]]:
    """
    Applies constant folding and consecutive filter merging on a list of IR steps.
    Returns (optimized_steps, list_of_applied_optimizations).
    """
    actions_taken: List[str] = []

    # Pass 1: Constant folding on all steps containing expressions
    folded_steps: List[IRStep] = []
    for step in steps:
        new_step = IRStep(
            step_id=step.step_id,
            op=step.op,
            input_ref=step.input_ref,
            output_ref=step.output_ref,
            details=dict(step.details),
            comment=step.comment
        )
        if step.op == "let" and "expr" in step.details:
            orig_str = step.details.get("expr_str", "")
            folded = fold_constants(step.details["expr"])
            new_str = expr_to_str(folded)
            if orig_str != new_str:
                actions_taken.append(f"Constant folded let '{step.output_ref}': {orig_str} -> {new_str}")
            new_step.details["expr"] = folded
            new_step.details["expr_str"] = new_str

        elif step.op == "filter" and "predicate" in step.details:
            orig_str = step.details.get("predicate_str", "")
            folded = fold_constants(step.details["predicate"])
            new_str = expr_to_str(folded)
            if orig_str != new_str:
                actions_taken.append(f"Constant folded filter on '{step.input_ref}': {orig_str} -> {new_str}")
            new_step.details["predicate"] = folded
            new_step.details["predicate_str"] = new_str

        folded_steps.append(new_step)

    # Pass 2: Merge consecutive filter steps
    merged_steps: List[IRStep] = []
    i = 0
    while i < len(folded_steps):
        current = folded_steps[i]

        # Check if current and next are both filters in the same chain
        if (
            current.op == "filter"
            and i + 1 < len(folded_steps)
            and folded_steps[i + 1].op == "filter"
            and folded_steps[i + 1].input_ref == current.output_ref
        ):
            nxt = folded_steps[i + 1]
            combined_pred = BinaryOp(
                op="and",
                left=current.details["predicate"],
                right=nxt.details["predicate"],
                line=nxt.details["predicate"].line,
                column=nxt.details["predicate"].column
            )
            # Fold if possible
            combined_pred = fold_constants(combined_pred)
            combined_str = expr_to_str(combined_pred)

            actions_taken.append(
                f"Merged consecutive filters ({current.details['predicate_str']}) and "
                f"({nxt.details['predicate_str']}) on '{current.input_ref}'"
            )

            merged_step = IRStep(
                step_id=current.step_id,
                op="filter",
                input_ref=current.input_ref,
                output_ref=nxt.output_ref,
                details={
                    "predicate": combined_pred,
                    "predicate_str": combined_str
                },
                comment=f"Combined filter: {combined_str}"
            )
            merged_steps.append(merged_step)
            i += 2  # Skipped next
        else:
            merged_steps.append(current)
            i += 1

    # Re-index step IDs sequentially
    for idx, s in enumerate(merged_steps, 1):
        s.step_id = idx

    return merged_steps, actions_taken
