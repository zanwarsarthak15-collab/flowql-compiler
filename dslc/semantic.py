"""
FlowQL Semantic Analyzer.

Performs symbol table management, schema propagation through pipeline stages,
and type checking on expressions. Generates standard diagnostic errors (E101-E108).
"""
from typing import Dict, List, Optional, Tuple
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
from dslc.errors import (
    CompileError,
    E101_UNDEFINED_NAME,
    E102_REDECLARATION,
    E103_UNKNOWN_COLUMN,
    E104_TYPE_MISMATCH,
    E105_NON_BOOL_FILTER,
    E106_NON_NUMERIC_AGG,
    E107_INVALID_LIMIT,
    E108_INVALID_PRINT,
    E109_CSV_SCHEMA_MISMATCH,
)


class SemanticAnalyzer:
    """
    Maintains symbol tables and validates schemas across all FlowQL statements.
    """

    def __init__(self, source_code: str = "", csv_schemas: Optional[Dict[str, List[str]]] = None):
        self.source_code = source_code
        self.source_lines = source_code.splitlines() if source_code else []
        self.csv_schemas = csv_schemas or {}  # dataset_name / filename -> [col1, col2]
        self.variables: Dict[str, str] = {}  # var_name -> type ('num', 'str', 'bool')
        self.tables: Dict[str, Dict[str, str]] = {}  # table_name -> {col_name: col_type}
        self.errors: List[CompileError] = []

    def _get_line_text(self, lineno: int) -> str:
        if 1 <= lineno <= len(self.source_lines):
            return self.source_lines[lineno - 1]
        return ""

    def _add_error(self, code: str, message: str, line: int, column: int):
        self.errors.append(CompileError(
            code=code,
            message=message,
            line=line,
            column=column,
            source_line=self._get_line_text(line)
        ))

    def analyze(self, program: Program) -> List[CompileError]:
        """Runs full semantic analysis on the given Program AST."""
        if not program or not program.statements:
            return self.errors

        for stmt in program.statements:
            self._visit_statement(stmt)

        return self.errors

    def _visit_statement(self, stmt: Stmt):
        if isinstance(stmt, DatasetDecl):
            self._visit_dataset_decl(stmt)
        elif isinstance(stmt, LetStmt):
            self._visit_let_stmt(stmt)
        elif isinstance(stmt, PipelineAssign):
            self._visit_pipeline_assign(stmt)
        elif isinstance(stmt, PrintStmt):
            self._visit_print_stmt(stmt)

    def _visit_dataset_decl(self, stmt: DatasetDecl):
        # E102: Check redeclaration
        if stmt.name in self.tables or stmt.name in self.variables:
            self._add_error(
                E102_REDECLARATION,
                f"Redeclaration of name '{stmt.name}'",
                stmt.line,
                stmt.column
            )
            return

        schema: Dict[str, str] = {}
        for col in stmt.columns:
            schema[col.name] = col.col_type
        self.tables[stmt.name] = schema

        # Check against actual CSV schema if available
        if self.csv_schemas:
            filename_only = stmt.path.replace("\\", "/").split("/")[-1]
            available_cols = (
                self.csv_schemas.get(stmt.name)
                or self.csv_schemas.get(stmt.path)
                or self.csv_schemas.get(filename_only)
            )
            if available_cols is not None:
                norm_avail = {c.strip().lower() for c in available_cols}
                for col in stmt.columns:
                    if col.name.strip().lower() not in norm_avail:
                        self._add_error(
                            E109_CSV_SCHEMA_MISMATCH,
                            f"Declared column '{col.name}' not found in CSV '{stmt.path}'. Available columns: {', '.join(available_cols)}",
                            col.line,
                            col.column
                        )

    def _visit_let_stmt(self, stmt: LetStmt):
        # E102: Check redeclaration
        if stmt.name in self.variables or stmt.name in self.tables:
            self._add_error(
                E102_REDECLARATION,
                f"Redeclaration of name '{stmt.name}'",
                stmt.line,
                stmt.column
            )
            return

        # Infer type of expression in scope without active columns
        expr_type = self._infer_expr_type(stmt.expr, current_schema=None)
        if expr_type:
            self.variables[stmt.name] = expr_type
        else:
            self.variables[stmt.name] = "num"  # Fallback to avoid cascade

    def _visit_pipeline_assign(self, stmt: PipelineAssign):
        # E102: Check target redeclaration
        if stmt.target in self.tables or stmt.target in self.variables:
            self._add_error(
                E102_REDECLARATION,
                f"Redeclaration of name '{stmt.target}'",
                stmt.line,
                stmt.column
            )

        # E101: Check source table exists
        if stmt.source_table not in self.tables:
            self._add_error(
                E101_UNDEFINED_NAME,
                f"Undefined table '{stmt.source_table}'",
                stmt.line,
                stmt.column
            )
            # Default empty schema so we don't crash
            self.tables[stmt.target] = {}
            return

        current_schema = dict(self.tables[stmt.source_table])

        # Propagate schema through pipeline stages
        for stage in stmt.stages:
            current_schema = self._apply_stage(stage, current_schema)

        self.tables[stmt.target] = current_schema

    def _apply_stage(self, stage: Stage, current_schema: Dict[str, str]) -> Dict[str, str]:
        if isinstance(stage, FilterStage):
            pred_type = self._infer_expr_type(stage.predicate, current_schema)
            if pred_type and pred_type != "bool":
                self._add_error(
                    E105_NON_BOOL_FILTER,
                    f"Filter expression must be boolean, got '{pred_type}'",
                    stage.line,
                    stage.column
                )
            return dict(current_schema)

        elif isinstance(stage, SelectStage):
            new_schema: Dict[str, str] = {}
            for col in stage.columns:
                if col not in current_schema:
                    self._add_error(
                        E103_UNKNOWN_COLUMN,
                        f"Unknown column '{col}' for current schema (available: {', '.join(current_schema.keys())})",
                        stage.line,
                        stage.column
                    )
                else:
                    new_schema[col] = current_schema[col]
            return new_schema

        elif isinstance(stage, GroupStage):
            # Check key_col
            if stage.key_col not in current_schema:
                self._add_error(
                    E103_UNKNOWN_COLUMN,
                    f"Unknown group key column '{stage.key_col}'",
                    stage.line,
                    stage.column
                )

            # Check agg_col
            if stage.agg_col not in current_schema:
                self._add_error(
                    E103_UNKNOWN_COLUMN,
                    f"Unknown aggregation column '{stage.agg_col}'",
                    stage.line,
                    stage.column
                )
            else:
                target_col_type = current_schema[stage.agg_col]
                agg_op = stage.agg_func.lower()
                if agg_op in ("sum", "avg") and target_col_type != "num":
                    self._add_error(
                        E106_NON_NUMERIC_AGG,
                        f"Cannot compute '{agg_op}' on non-numeric column '{stage.agg_col}' (type: {target_col_type})",
                        stage.line,
                        stage.column
                    )

            key_type = current_schema.get(stage.key_col, "str")
            agg_output_col = f"{stage.agg_func.lower()}_{stage.agg_col}"
            # Aggregation output is numeric
            return {stage.key_col: key_type, agg_output_col: "num"}

        elif isinstance(stage, SortStage):
            if stage.sort_col not in current_schema:
                self._add_error(
                    E103_UNKNOWN_COLUMN,
                    f"Unknown column '{stage.sort_col}' in sort stage",
                    stage.line,
                    stage.column
                )
            return dict(current_schema)

        elif isinstance(stage, LimitStage):
            if not isinstance(stage.count, int) or stage.count <= 0:
                self._add_error(
                    E107_INVALID_LIMIT,
                    f"Limit value must be a positive integer, got '{stage.count}'",
                    stage.line,
                    stage.column
                )
            return dict(current_schema)

        return current_schema

    def _visit_print_stmt(self, stmt: PrintStmt):
        # E108: print of an undefined or non-table name
        if stmt.table_name not in self.tables:
            if stmt.table_name in self.variables:
                self._add_error(
                    E108_INVALID_PRINT,
                    f"Cannot print variable '{stmt.table_name}'; print requires a dataset or pipeline table",
                    stmt.line,
                    stmt.column
                )
            else:
                self._add_error(
                    E108_INVALID_PRINT,
                    f"Print of undefined table '{stmt.table_name}'",
                    stmt.line,
                    stmt.column
                )

    def _infer_expr_type(self, expr: Expr, current_schema: Optional[Dict[str, str]]) -> Optional[str]:
        if isinstance(expr, NumberLiteral):
            return "num"
        elif isinstance(expr, StringLiteral):
            return "str"
        elif isinstance(expr, BoolLiteral):
            return "bool"
        elif isinstance(expr, Identifier):
            # Check current schema columns first
            if current_schema is not None and expr.name in current_schema:
                return current_schema[expr.name]
            # Check variables in scope
            if expr.name in self.variables:
                return self.variables[expr.name]
            # If not found
            if current_schema is not None:
                self._add_error(
                    E103_UNKNOWN_COLUMN,
                    f"Unknown identifier '{expr.name}' in expression (not in schema or let variables)",
                    expr.line,
                    expr.column
                )
            else:
                self._add_error(
                    E101_UNDEFINED_NAME,
                    f"Undefined variable '{expr.name}'",
                    expr.line,
                    expr.column
                )
            return None

        elif isinstance(expr, UnaryOp):
            inner_type = self._infer_expr_type(expr.expr, current_schema)
            if not inner_type:
                return None
            if expr.op == "-":
                if inner_type != "num":
                    self._add_error(
                        E104_TYPE_MISMATCH,
                        f"Unary '-' expects 'num', got '{inner_type}'",
                        expr.line,
                        expr.column
                    )
                    return None
                return "num"
            elif expr.op == "not":
                if inner_type != "bool":
                    self._add_error(
                        E104_TYPE_MISMATCH,
                        f"Unary 'not' expects 'bool', got '{inner_type}'",
                        expr.line,
                        expr.column
                    )
                    return None
                return "bool"

        elif isinstance(expr, BinaryOp):
            left_t = self._infer_expr_type(expr.left, current_schema)
            right_t = self._infer_expr_type(expr.right, current_schema)
            if not left_t or not right_t:
                return None

            op = expr.op
            # Logical AND, OR
            if op in ("and", "or"):
                if left_t != "bool" or right_t != "bool":
                    self._add_error(
                        E104_TYPE_MISMATCH,
                        f"Operator '{op}' requires boolean operands, got '{left_t}' and '{right_t}'",
                        expr.line,
                        expr.column
                    )
                    return None
                return "bool"

            # Equality ==, !=
            if op in ("==", "!="):
                if left_t != right_t:
                    self._add_error(
                        E104_TYPE_MISMATCH,
                        f"Comparison '{op}' requires matching types, got '{left_t}' and '{right_t}'",
                        expr.line,
                        expr.column
                    )
                    return None
                return "bool"

            # Ordering <, <=, >, >=
            if op in ("<", "<=", ">", ">="):
                if left_t != right_t or left_t not in ("num", "str"):
                    self._add_error(
                        E104_TYPE_MISMATCH,
                        f"Comparison '{op}' requires comparable types ('num' or 'str'), got '{left_t}' and '{right_t}'",
                        expr.line,
                        expr.column
                    )
                    return None
                return "bool"

            # Arithmetic +
            if op == "+":
                if left_t == "num" and right_t == "num":
                    return "num"
                elif left_t == "str" and right_t == "str":
                    return "str"
                else:
                    self._add_error(
                        E104_TYPE_MISMATCH,
                        f"Operator '+' requires two 'num' or two 'str', got '{left_t}' and '{right_t}'",
                        expr.line,
                        expr.column
                    )
                    return None

            # Arithmetic -, *, /, %
            if op in ("-", "*", "/", "%"):
                if left_t != "num" or right_t != "num":
                    self._add_error(
                        E104_TYPE_MISMATCH,
                        f"Arithmetic '{op}' requires numeric operands, got '{left_t}' and '{right_t}'",
                        expr.line,
                        expr.column
                    )
                    return None
                return "num"

        return None
