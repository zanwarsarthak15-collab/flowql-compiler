"""
Tests for Python and SQL Backends, including SQLite Equivalence on sales.csv.
"""
import sqlite3
from pathlib import Path
import pandas as pd
import pytest
from dslc.compiler import compile_flowql


def test_generated_python_and_sql_match_on_sales_csv():
    """
    Directly compiles a FlowQL program to Python and SQL, executes the generated Python
    script and executes the generated SQL query (in SQLite) on examples/data/sales.csv,
    and asserts that both outputs are identical.
    """
    sales_csv_path = Path(__file__).parent.parent / "examples" / "data" / "sales.csv"
    assert sales_csv_path.exists(), "sales.csv must exist"

    # Use forward slashes for path in FlowQL load statement
    csv_str = str(sales_csv_path).replace("\\", "/")

    source = f"""
    dataset sales(region: str, product: str, amount: num, units: num) = load "{csv_str}";
    let threshold = 100;
    top = sales
        | filter amount > threshold and units >= 2
        | select region, amount
        | group region sum amount
        | sort sum_amount desc
        | limit 5;
    print top;
    """

    res_py = compile_flowql(source, target="python")
    res_sql = compile_flowql(source, target="sql")

    assert res_py["success"] is True, f"Python compile failed: {res_py['errors']}"
    assert res_sql["success"] is True, f"SQL compile failed: {res_sql['errors']}"

    # 1. Execute generated Python code
    py_env = {}
    exec(res_py["target_code"], py_env)
    assert "top" in py_env, "Generated Python code must produce 'top' DataFrame"
    py_df = py_env["top"]

    # 2. Execute generated SQL code in SQLite
    conn = sqlite3.connect(":memory:")
    raw_df = pd.read_csv(sales_csv_path)
    raw_df.to_sql("sales", conn, index=False)

    clean_sql = "\n".join([line for line in res_sql["target_code"].splitlines() if not line.strip().startswith("--")])
    sql_df = pd.read_sql_query(clean_sql, conn)
    conn.close()

    # 3. Verify equivalence of generated outputs
    assert len(py_df) == len(sql_df), f"Row count mismatch: Python={len(py_df)}, SQL={len(sql_df)}"
    assert list(py_df.columns) == list(sql_df.columns), f"Columns mismatch: {py_df.columns} vs {sql_df.columns}"

    # Compare values directly
    for col in py_df.columns:
        assert list(py_df[col]) == list(sql_df[col]), f"Column values mismatch for {col}"

    pd.testing.assert_frame_equal(py_df, sql_df, check_dtype=False)


def test_python_and_sql_avg_pipeline_equivalence():
    """
    Tests avg aggregation and filtering equivalence between Python and SQLite.
    """
    sales_csv_path = Path(__file__).parent.parent / "examples" / "data" / "sales.csv"
    csv_str = str(sales_csv_path).replace("\\", "/")

    source = f"""
    dataset sales(region: str, product: str, amount: num, units: num) = load "{csv_str}";
    let min_amount = 50;
    regional_avg = sales
        | filter amount > min_amount
        | group region avg amount
        | sort avg_amount desc
        | limit 3;
    print regional_avg;
    """

    res_py = compile_flowql(source, target="python")
    res_sql = compile_flowql(source, target="sql")

    assert res_py["success"] is True
    assert res_sql["success"] is True

    # Execute Python
    py_env = {}
    exec(res_py["target_code"], py_env)
    py_df = py_env["regional_avg"]

    # Execute SQL in SQLite
    conn = sqlite3.connect(":memory:")
    raw_df = pd.read_csv(sales_csv_path)
    raw_df.to_sql("sales", conn, index=False)
    clean_sql = "\n".join([line for line in res_sql["target_code"].splitlines() if not line.strip().startswith("--")])
    sql_df = pd.read_sql_query(clean_sql, conn)
    conn.close()

    assert list(py_df.columns) == list(sql_df.columns)
    assert len(py_df) == len(sql_df)
    for col in py_df.columns:
        assert list(py_df[col]) == list(sql_df[col])


def test_select_and_sort_pipeline_structure():
    """
    Tests select and sort stages structure.
    """
    source = """
    dataset sales(region: str, product: str, amount: num, units: num) = load "data.csv";
    res = sales
        | select product, amount
        | sort amount desc
        | limit 2;
    print res;
    """
    res_sql = compile_flowql(source, target="sql")
    assert "WITH" in res_sql["target_code"]
    assert "res_step1 AS" in res_sql["target_code"]
    assert "res_step2 AS" in res_sql["target_code"]
    assert "LIMIT 2" in res_sql["target_code"]
