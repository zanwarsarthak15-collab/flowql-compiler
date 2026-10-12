"""
Tests for FlowQL Semantic Analyzer.
"""
import pytest
from dslc.parser import FlowQLParser
from dslc.semantic import SemanticAnalyzer
from dslc.errors import (
    E101_UNDEFINED_NAME,
    E102_REDECLARATION,
    E103_UNKNOWN_COLUMN,
    E104_TYPE_MISMATCH,
    E105_NON_BOOL_FILTER,
    E106_NON_NUMERIC_AGG,
    E107_INVALID_LIMIT,
    E108_INVALID_PRINT,
)


def run_semantic(source: str):
    parser = FlowQLParser()
    ast, parse_errors = parser.parse(source)
    assert len(parse_errors) == 0, f"Parse errors: {parse_errors}"
    analyzer = SemanticAnalyzer(source)
    errors = analyzer.analyze(ast)
    return analyzer, errors


def test_e101_undefined_table():
    source = "res = missing_table | limit 5; print res;"
    _, errors = run_semantic(source)
    assert any(e.code == E101_UNDEFINED_NAME for e in errors)


def test_e102_redeclaration():
    source = """
    dataset sales(a: num) = load "a.csv";
    let sales = 10;
    print sales;
    """
    _, errors = run_semantic(source)
    assert any(e.code == E102_REDECLARATION for e in errors)


def test_e103_unknown_column():
    source = """
    dataset sales(region: str, amount: num) = load "a.csv";
    res = sales | select non_existent;
    print res;
    """
    _, errors = run_semantic(source)
    assert any(e.code == E103_UNKNOWN_COLUMN for e in errors)


def test_e104_type_mismatch():
    source = """
    dataset sales(region: str, amount: num) = load "a.csv";
    res = sales | filter region > 10;
    print res;
    """
    _, errors = run_semantic(source)
    assert any(e.code == E104_TYPE_MISMATCH for e in errors)


def test_e105_non_bool_filter():
    source = """
    dataset sales(region: str, amount: num) = load "a.csv";
    res = sales | filter amount + 5;
    print res;
    """
    _, errors = run_semantic(source)
    assert any(e.code == E105_NON_BOOL_FILTER for e in errors)


def test_e106_non_numeric_agg():
    source = """
    dataset sales(region: str, product: str) = load "a.csv";
    res = sales | group region sum product;
    print res;
    """
    _, errors = run_semantic(source)
    assert any(e.code == E106_NON_NUMERIC_AGG for e in errors)


def test_e107_invalid_limit():
    source = """
    dataset sales(region: str) = load "a.csv";
    res = sales | limit 0;
    print res;
    """
    _, errors = run_semantic(source)
    assert any(e.code == E107_INVALID_LIMIT for e in errors)


def test_e108_invalid_print():
    source = """
    let x = 42;
    print x;
    """
    _, errors = run_semantic(source)
    assert any(e.code == E108_INVALID_PRINT for e in errors)


def test_schema_propagation_group_and_select():
    source = """
    dataset sales(region: str, product: str, amount: num) = load "a.csv";
    t1 = sales | group region sum amount;
    # t1 schema should have region: str and sum_amount: num
    t2 = t1 | select region, sum_amount | sort sum_amount desc;
    print t2;
    """
    analyzer, errors = run_semantic(source)
    assert len(errors) == 0
    assert "t1" in analyzer.tables
    assert analyzer.tables["t1"] == {"region": "str", "sum_amount": "num"}
    assert analyzer.tables["t2"] == {"region": "str", "sum_amount": "num"}


def test_multiple_semantic_errors_in_one_run():
    # Program containing multiple semantic errors: unknown columns (E103), non-bool filter (E105), invalid limit (E107)
    source = """
    dataset sales(region: str, amount: num) = load "data.csv";
    bad = sales
        | filter amount + 10
        | select unknown_col1, unknown_col2
        | limit 0;
    print bad;
    """
    _, errors = run_semantic(source)
    assert len(errors) >= 3, f"Expected multiple errors, got {len(errors)}: {errors}"
    codes = [e.code for e in errors]
    assert E103_UNKNOWN_COLUMN in codes
    assert E105_NON_BOOL_FILTER in codes
    assert E107_INVALID_LIMIT in codes


def test_semantic_error_example_files():
    from pathlib import Path
    examples_dir = Path(__file__).parent.parent / "examples"
    
    files_and_expected_codes = [
        ("semantic_err_undefined_table.fql", E101_UNDEFINED_NAME),
        ("semantic_err_redeclaration.fql", E102_REDECLARATION),
        ("semantic_err_unknown_column.fql", E103_UNKNOWN_COLUMN),
        ("semantic_err_type_mismatch.fql", E104_TYPE_MISMATCH),
        ("semantic_err_non_numeric_agg.fql", E106_NON_NUMERIC_AGG),
        ("semantic_err_multi_errors.fql", E103_UNKNOWN_COLUMN),
    ]
    for filename, expected_code in files_and_expected_codes:
        filepath = examples_dir / filename
        source = filepath.read_text(encoding="utf-8")
        _, errors = run_semantic(source)
        assert len(errors) >= 1, f"Expected errors in {filename}"
        assert any(e.code == expected_code for e in errors), f"Expected {expected_code} in {filename}, got {[e.code for e in errors]}"

