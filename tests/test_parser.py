"""
Tests for FlowQL Parser.
"""
import pytest
from dslc.parser import FlowQLParser
from dslc.ast_nodes import (
    Program,
    DatasetDecl,
    LetStmt,
    PipelineAssign,
    PrintStmt,
    FilterStage,
    SelectStage,
    GroupStage,
    SortStage,
    LimitStage,
    BinaryOp,
)
from dslc.errors import E010_UNEXPECTED_TOKEN, E011_UNEXPECTED_EOF


def test_parser_valid_program():
    source = """
    dataset sales(region: str, amount: num) = load "sales.csv";
    let min_val = 50;
    res = sales
        | filter amount > min_val
        | select region, amount
        | group region sum amount
        | sort sum_amount desc
        | limit 10;
    print res;
    """
    parser = FlowQLParser()
    ast, errors = parser.parse(source)

    assert len(errors) == 0
    assert isinstance(ast, Program)
    assert len(ast.statements) == 4

    # Check statement types
    assert isinstance(ast.statements[0], DatasetDecl)
    assert ast.statements[0].name == "sales"
    assert len(ast.statements[0].columns) == 2

    assert isinstance(ast.statements[1], LetStmt)
    assert ast.statements[1].name == "min_val"

    assert isinstance(ast.statements[2], PipelineAssign)
    pipe = ast.statements[2]
    assert pipe.target == "res"
    assert pipe.source_table == "sales"
    assert len(pipe.stages) == 5
    assert isinstance(pipe.stages[0], FilterStage)
    assert isinstance(pipe.stages[1], SelectStage)
    assert isinstance(pipe.stages[2], GroupStage)
    assert isinstance(pipe.stages[3], SortStage)
    assert isinstance(pipe.stages[4], LimitStage)

    assert isinstance(ast.statements[3], PrintStmt)
    assert ast.statements[3].table_name == "res"


def test_parser_precedence():
    source = "let x = 1 + 2 * 3;"
    parser = FlowQLParser()
    ast, errors = parser.parse(source)
    assert len(errors) == 0
    let = ast.statements[0]
    # In 1 + 2 * 3, '+' should be the top-level binary op, right is 2 * 3
    assert isinstance(let.expr, BinaryOp)
    assert let.expr.op == "+"
    assert isinstance(let.expr.right, BinaryOp)
    assert let.expr.right.op == "*"


def test_parser_syntax_error_recovery():
    # Two statements, both having errors, recovering at ';'
    source = """
    dataset bad_table( = load "data.csv";
    let y = 10;
    bad_pipeline = sales | filter ;
    print y;
    """
    parser = FlowQLParser()
    ast, errors = parser.parse(source)

    assert len(errors) >= 2
    # At least two E010 errors should have been captured
    e010_errors = [e for e in errors if e.code == E010_UNEXPECTED_TOKEN]
    assert len(e010_errors) >= 2


def test_parser_unexpected_eof():
    source = "let incomplete = "
    parser = FlowQLParser()
    ast, errors = parser.parse(source)

    assert len(errors) >= 1
    assert any(e.code in (E010_UNEXPECTED_TOKEN, E011_UNEXPECTED_EOF) for e in errors)


def test_parser_syntax_error_examples():
    from pathlib import Path
    examples_dir = Path(__file__).parent.parent / "examples"
    parser = FlowQLParser()

    syntax_err_files = [
        "syntax_error_trailing_operator.fql",
        "syntax_error_missing_semicolon.fql",
        "syntax_error_bad_stage_token.fql"
    ]
    for filename in syntax_err_files:
        filepath = examples_dir / filename
        source = filepath.read_text(encoding="utf-8")
        _, errors = parser.parse(source)
        assert len(errors) >= 1, f"Expected syntax error in {filename}"
        assert any(e.code in (E010_UNEXPECTED_TOKEN, E011_UNEXPECTED_EOF) for e in errors)


def test_parser_valid_examples():
    from pathlib import Path
    examples_dir = Path(__file__).parent.parent / "examples"
    parser = FlowQLParser()

    valid_files = [
        "valid_top_regions.fql",
        "valid_filter_sort.fql",
        "valid_product_summary.fql",
        "valid_average_ticket.fql"
    ]
    for filename in valid_files:
        filepath = examples_dir / filename
        source = filepath.read_text(encoding="utf-8")
        ast, errors = parser.parse(source)
        assert len(errors) == 0, f"Unexpected error in {filename}: {errors}"
        assert ast is not None

