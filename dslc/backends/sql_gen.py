"""
FlowQL to SQL Code Generator.

Generates ANSI-compliant SQL queries using Common Table Expressions (CTEs),
one CTE per pipeline stage. Each CTE is annotated with comments linking back
to the FlowQL source stage.
"""
from typing import List, Dict, Any, Optional
from dslc.ir import IRStep
from dslc.ast_nodes import (
    Expr,
    NumberLiteral,
    StringLiteral,
    BoolLiteral,
    Identifier,
    BinaryOp,
    UnaryOp,
)


def expr_to_sql(expr: Expr, var_values: Dict[str, str]) -> str:
    """Converts a FlowQL expression AST to standard SQL syntax."""
    if isinstance(expr, NumberLiteral):
        return str(expr.value)
    elif isinstance(expr, StringLiteral):
        escaped = expr.value.replace("'", "''")
        return f"'{escaped}'"
    elif isinstance(expr, BoolLiteral):
        return "TRUE" if expr.value else "FALSE"
    elif isinstance(expr, Identifier):
        if expr.name in var_values:
            return var_values[expr.name]
        return expr.name
    elif isinstance(expr, UnaryOp):
        sub = expr_to_sql(expr.expr, var_values)
        if expr.op == "not":
            return f"(NOT {sub})"
        return f"(-{sub})"
    elif isinstance(expr, BinaryOp):
        left = expr_to_sql(expr.left, var_values)
        right = expr_to_sql(expr.right, var_values)
        op = expr.op
        if op == "and":
            return f"({left} AND {right})"
        elif op == "or":
            return f"({left} OR {right})"
        elif op == "==":
            return f"({left} = {right})"
        elif op == "!=":
            return f"({left} <> {right})"
        else:
            return f"({left} {op} {right})"
    return ""


class SQLGenerator:
    """Generates CTE-based ANSI SQL statements from FlowQL IR steps."""

    def generate(self, steps: List[IRStep]) -> str:
        var_values: Dict[str, str] = {}
        cte_blocks: List[str] = []
        final_table: Optional[str] = None
        print_target: Optional[str] = None

        for step in steps:
            if step.op == "load":
                # Dataset is treated as the base table name
                pass

            elif step.op == "let":
                expr_obj = step.details.get("expr")
                if isinstance(expr_obj, Expr):
                    var_values[step.output_ref] = expr_to_sql(expr_obj, var_values)
                else:
                    var_values[step.output_ref] = str(step.details.get("expr_str", ""))

            elif step.op == "alias":
                comment = f"    -- [FlowQL: Step {step.step_id}] {step.comment}"
                body = (
                    f"{step.output_ref} AS (\n"
                    f"{comment}\n"
                    f"    SELECT *\n"
                    f"    FROM {step.input_ref}\n"
                    f")"
                )
                cte_blocks.append(body)
                final_table = step.output_ref

            elif step.op == "filter":
                pred_obj = step.details.get("predicate")
                if isinstance(pred_obj, Expr):
                    pred_sql = expr_to_sql(pred_obj, var_values)
                else:
                    pred_sql = step.details.get("predicate_str", "TRUE")

                comment = f"    -- [FlowQL: Step {step.step_id}] {step.comment}"
                body = (
                    f"{step.output_ref} AS (\n"
                    f"{comment}\n"
                    f"    SELECT *\n"
                    f"    FROM {step.input_ref}\n"
                    f"    WHERE {pred_sql}\n"
                    f")"
                )
                cte_blocks.append(body)
                final_table = step.output_ref

            elif step.op == "select":
                cols = step.details.get("columns", ["*"])
                cols_sql = ", ".join(cols)
                comment = f"    -- [FlowQL: Step {step.step_id}] {step.comment}"
                body = (
                    f"{step.output_ref} AS (\n"
                    f"{comment}\n"
                    f"    SELECT {cols_sql}\n"
                    f"    FROM {step.input_ref}\n"
                    f")"
                )
                cte_blocks.append(body)
                final_table = step.output_ref

            elif step.op == "group":
                key_col = step.details.get("key_col", "")
                agg_func = step.details.get("agg_func", "SUM").upper()
                agg_col = step.details.get("agg_col", "")
                res_col = step.details.get("result_col", f"{agg_func.lower()}_{agg_col}")

                comment = f"    -- [FlowQL: Step {step.step_id}] {step.comment}"
                body = (
                    f"{step.output_ref} AS (\n"
                    f"{comment}\n"
                    f"    SELECT\n"
                    f"        {key_col},\n"
                    f"        {agg_func}({agg_col}) AS {res_col}\n"
                    f"    FROM {step.input_ref}\n"
                    f"    GROUP BY {key_col}\n"
                    f")"
                )
                cte_blocks.append(body)
                final_table = step.output_ref

            elif step.op == "sort":
                col = step.details.get("column", "")
                direction = step.details.get("direction", "ASC").upper()
                comment = f"    -- [FlowQL: Step {step.step_id}] {step.comment}"
                body = (
                    f"{step.output_ref} AS (\n"
                    f"{comment}\n"
                    f"    SELECT *\n"
                    f"    FROM {step.input_ref}\n"
                    f"    ORDER BY {col} {direction}\n"
                    f")"
                )
                cte_blocks.append(body)
                final_table = step.output_ref

            elif step.op == "limit":
                count = step.details.get("count", 10)
                comment = f"    -- [FlowQL: Step {step.step_id}] {step.comment}"
                body = (
                    f"{step.output_ref} AS (\n"
                    f"{comment}\n"
                    f"    SELECT *\n"
                    f"    FROM {step.input_ref}\n"
                    f"    LIMIT {count}\n"
                    f")"
                )
                cte_blocks.append(body)
                final_table = step.output_ref

            elif step.op == "print":
                print_target = step.details.get("table", step.input_ref)

        lines: List[str] = [
            "-- =====================================================================",
            "-- Generated by FlowQL Compiler (SQL / ANSI CTE Target)",
            "-- =====================================================================",
            ""
        ]

        target_table = print_target or final_table
        if cte_blocks:
            lines.append("WITH " + ",\n\n".join(cte_blocks))
            lines.append("")
            if target_table:
                lines.append(f"SELECT * FROM {target_table};")
            else:
                lines.append("SELECT 1;")
        else:
            if target_table:
                lines.append(f"SELECT * FROM {target_table};")
            else:
                lines.append("-- Empty pipeline")

        return "\n".join(lines)
