"""
FlowQL Syntactic Analyzer (Parser).

Implemented using PLY (Python Lex-Yacc).
Builds an Abstract Syntax Tree (AST) of dataclasses from FlowQL tokens,
reports syntax errors with line/column (E010, E011), and recovers at semicolons
to capture multiple syntax errors in a single compilation run.
"""
from typing import Tuple, List, Optional
import ply.yacc as yacc

from dslc.lexer import tokens, FlowQLLexer, find_column, get_line_text
from dslc.errors import CompileError, E010_UNEXPECTED_TOKEN, E011_UNEXPECTED_EOF
from dslc.ast_nodes import (
    Program,
    Stmt,
    DatasetDecl,
    ColumnDef,
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

# Operator precedence rules (highest to lowest)
precedence = (
    ('left', 'OR'),
    ('left', 'AND'),
    ('right', 'NOT'),
    ('nonassoc', 'EQ', 'NEQ', 'LT', 'LE', 'GT', 'GE'),
    ('left', 'PLUS', 'MINUS'),
    ('left', 'TIMES', 'DIVIDE', 'MODULO'),
    ('right', 'UMINUS'),
)

_current_errors: List[CompileError] = []
_current_source: str = ""


# Grammar Rules
def p_program(p):
    '''program : statement_list'''
    statements = [stmt for stmt in p[1] if stmt is not None]
    p[0] = Program(statements=statements, line=1, column=1)


def p_statement_list(p):
    '''statement_list : statement_list statement
                      | empty'''
    if len(p) == 3:
        p[0] = p[1] + ([p[2]] if p[2] is not None else [])
    else:
        p[0] = []


def p_empty(p):
    'empty :'
    pass


def p_statement(p):
    '''statement : dataset_decl
                 | let_stmt
                 | pipeline_assign
                 | print_stmt'''
    p[0] = p[1]


# Error recovery: discard bad tokens until the next semicolon
def p_statement_error(p):
    '''statement : error SEMICOLON'''
    p[0] = None


def p_dataset_decl(p):
    'dataset_decl : DATASET ID LPAREN column_list RPAREN ASSIGN LOAD STRING SEMICOLON'
    col = find_column(_current_source, p.slice[1])
    p[0] = DatasetDecl(
        name=p[2],
        columns=p[4],
        path=p[8],
        line=p.lineno(1),
        column=col
    )


def p_column_list(p):
    '''column_list : column_list COMMA column
                   | column'''
    if len(p) == 4:
        p[0] = p[1] + [p[3]]
    else:
        p[0] = [p[1]]


def p_column(p):
    'column : ID COLON type'
    col = find_column(_current_source, p.slice[1])
    p[0] = ColumnDef(
        name=p[1],
        col_type=p[3],
        line=p.lineno(1),
        column=col
    )


def p_type(p):
    '''type : TYPE_NUM
            | TYPE_STR
            | TYPE_BOOL'''
    p[0] = p[1]


def p_let_stmt(p):
    'let_stmt : LET ID ASSIGN expr SEMICOLON'
    col = find_column(_current_source, p.slice[1])
    p[0] = LetStmt(
        name=p[2],
        expr=p[4],
        line=p.lineno(1),
        column=col
    )


def p_pipeline_assign(p):
    'pipeline_assign : ID ASSIGN pipeline SEMICOLON'
    source_table, stages = p[3]
    col = find_column(_current_source, p.slice[1])
    p[0] = PipelineAssign(
        target=p[1],
        source_table=source_table,
        stages=stages,
        line=p.lineno(1),
        column=col
    )


def p_pipeline(p):
    '''pipeline : ID stage_list'''
    p[0] = (p[1], p[2])


def p_stage_list(p):
    '''stage_list : stage_list PIPE stage
                  | empty'''
    if len(p) == 4:
        p[0] = p[1] + [p[3]]
    else:
        p[0] = []


def p_stage_filter(p):
    'stage : FILTER expr'
    col = find_column(_current_source, p.slice[1])
    p[0] = FilterStage(
        predicate=p[2],
        line=p.lineno(1),
        column=col
    )


def p_stage_select(p):
    'stage : SELECT id_list'
    col = find_column(_current_source, p.slice[1])
    p[0] = SelectStage(
        columns=p[2],
        line=p.lineno(1),
        column=col
    )


def p_id_list(p):
    '''id_list : id_list COMMA ID
               | ID'''
    if len(p) == 4:
        p[0] = p[1] + [p[3]]
    else:
        p[0] = [p[1]]


def p_stage_group(p):
    'stage : GROUP ID agg ID'
    col = find_column(_current_source, p.slice[1])
    p[0] = GroupStage(
        key_col=p[2],
        agg_func=p[3],
        agg_col=p[4],
        line=p.lineno(1),
        column=col
    )


def p_agg(p):
    '''agg : SUM
           | AVG
           | MIN
           | MAX
           | COUNT'''
    p[0] = p[1]


def p_stage_sort(p):
    '''stage : SORT ID opt_direction'''
    col = find_column(_current_source, p.slice[1])
    p[0] = SortStage(
        sort_col=p[2],
        direction=p[3],
        line=p.lineno(1),
        column=col
    )


def p_opt_direction(p):
    '''opt_direction : ASC
                     | DESC
                     | empty'''
    p[0] = p[1] if p[1] else 'asc'


def p_stage_limit(p):
    'stage : LIMIT NUMBER'
    col = find_column(_current_source, p.slice[1])
    p[0] = LimitStage(
        count=p[2],
        line=p.lineno(1),
        column=col
    )


def p_print_stmt(p):
    'print_stmt : PRINT ID SEMICOLON'
    col = find_column(_current_source, p.slice[1])
    p[0] = PrintStmt(
        table_name=p[2],
        line=p.lineno(1),
        column=col
    )


# Expressions
def p_expr_binary(p):
    '''expr : expr PLUS expr
            | expr MINUS expr
            | expr TIMES expr
            | expr DIVIDE expr
            | expr MODULO expr
            | expr EQ expr
            | expr NEQ expr
            | expr LT expr
            | expr LE expr
            | expr GT expr
            | expr GE expr
            | expr AND expr
            | expr OR expr'''
    col = find_column(_current_source, p.slice[2])
    p[0] = BinaryOp(
        op=p[2],
        left=p[1],
        right=p[3],
        line=p.lineno(2),
        column=col
    )


def p_expr_unary_minus(p):
    'expr : MINUS expr %prec UMINUS'
    col = find_column(_current_source, p.slice[1])
    p[0] = UnaryOp(
        op='-',
        expr=p[2],
        line=p.lineno(1),
        column=col
    )


def p_expr_unary_not(p):
    'expr : NOT expr'
    col = find_column(_current_source, p.slice[1])
    p[0] = UnaryOp(
        op='not',
        expr=p[2],
        line=p.lineno(1),
        column=col
    )


def p_expr_paren(p):
    'expr : LPAREN expr RPAREN'
    p[0] = p[2]


def p_expr_number(p):
    'expr : NUMBER'
    col = find_column(_current_source, p.slice[1])
    p[0] = NumberLiteral(
        value=p[1],
        line=p.lineno(1),
        column=col
    )


def p_expr_string(p):
    'expr : STRING'
    col = find_column(_current_source, p.slice[1])
    p[0] = StringLiteral(
        value=p[1],
        line=p.lineno(1),
        column=col
    )


def p_expr_bool_true(p):
    'expr : TRUE'
    col = find_column(_current_source, p.slice[1])
    p[0] = BoolLiteral(
        value=True,
        line=p.lineno(1),
        column=col
    )


def p_expr_bool_false(p):
    'expr : FALSE'
    col = find_column(_current_source, p.slice[1])
    p[0] = BoolLiteral(
        value=False,
        line=p.lineno(1),
        column=col
    )


def p_expr_id(p):
    'expr : ID'
    col = find_column(_current_source, p.slice[1])
    p[0] = Identifier(
        name=p[1],
        line=p.lineno(1),
        column=col
    )


def p_error(p):
    global _current_errors, _current_source
    if p:
        col = find_column(_current_source, p)
        line_text = get_line_text(_current_source, p.lineno)
        _current_errors.append(CompileError(
            code=E010_UNEXPECTED_TOKEN,
            message=f"Unexpected token '{p.value}' ({p.type})",
            line=p.lineno,
            column=col,
            source_line=line_text
        ))
    else:
        lines = _current_source.splitlines()
        last_line_num = len(lines) if lines else 1
        last_line = lines[-1] if lines else ""
        _current_errors.append(CompileError(
            code=E011_UNEXPECTED_EOF,
            message="Unexpected end of input",
            line=last_line_num,
            column=len(last_line) + 1,
            source_line=last_line
        ))


class FlowQLParser:
    """PLY-based parser wrapper that tracks syntax errors and constructs Program AST."""

    def __init__(self):
        self.parser = yacc.yacc(debug=False, write_tables=False)

    def parse(self, source: str) -> Tuple[Optional[Program], List[CompileError]]:
        global _current_errors, _current_source
        _current_errors = []
        _current_source = source

        lexer_instance = FlowQLLexer()
        # Pre-tokenize to check lexical errors
        _, lex_errors = lexer_instance.tokenize(source)
        _current_errors.extend(lex_errors)

        # Reset lexer for parser
        lexer_instance.lexer.lineno = 1
        lexer_instance.lexer.errors = []
        lexer_instance.lexer.input(source)

        ast = self.parser.parse(source, lexer=lexer_instance.lexer)
        return ast, list(_current_errors)
