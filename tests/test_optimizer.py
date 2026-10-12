"""
Tests for FlowQL Optimizer.
"""
import pytest
from dslc.compiler import compile_flowql
from dslc.parser import FlowQLParser
from dslc.ir import IRGenerator
from dslc.optimizer import optimize_ir, fold_constants
from dslc.ast_nodes import BinaryOp, NumberLiteral, BoolLiteral


def test_constant_folding_arithmetic():
    source = """
    dataset sales(region: str, amount: num) = load "data.csv";
    let threshold = 10 * 5 + 50; # should fold to 100
    res = sales | filter amount > threshold;
    print res;
    """
    res = compile_flowql(source, target="python", optimize=True)
    assert res["success"] is True

    # Find the 'let' step in IR
    let_step = next(s for s in res["ir"] if s["op"] == "let")
    assert let_step["details"]["expr_str"] == "100"
    assert any("Constant folded" in note for note in res["optimizations"])


def test_consecutive_filter_merging():
    source = """
    dataset sales(region: str, amount: num, units: num) = load "data.csv";
    res = sales
        | filter amount > 100
        | filter units >= 2;
    print res;
    """
    res = compile_flowql(source, target="python", optimize=True)
    assert res["success"] is True

    # After optimization, there should only be 1 filter step combining both
    filter_steps = [s for s in res["ir"] if s["op"] == "filter"]
    assert len(filter_steps) == 1
    assert "and" in filter_steps[0]["details"]["predicate_str"]
    assert any("Merged consecutive filters" in note for note in res["optimizations"])
