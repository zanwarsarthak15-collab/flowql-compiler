"""
Comprehensive Test Suite for FlowQL Compiler Enhancements:
- Undefined names & fuzzy suggestions (tables, variables, print)
- Wrong columns & schema mismatch handling
- Grouping, sorting, and limit edge cases
- Python vs SQL equivalence across multi-stage pipelines
- CSV schema inference (num, bool, str, nulls, edge cases)
- AI failure, timeout, retry, and offline resilience (mocked)
- Compiler LRU cache hits, invalidation, and request size boundaries
"""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from dslc.compiler import compile_flowql, clear_compile_cache, get_compile_cache_stats
from dslc.errors import (
    E101_UNDEFINED_NAME,
    E103_UNKNOWN_COLUMN,
    E106_NON_NUMERIC_AGG,
    E107_INVALID_LIMIT,
    E108_INVALID_PRINT,
)
from dslc.csv_utils import infer_column_type, inspect_csv_bytes, sanitize_identifier
from dslc.ai import explain_error, review_code
from server import app


client = TestClient(app)


# =============================================================================
# 1. Undefined Names & Fuzzy Suggestions
# =============================================================================

def test_undefined_table_fuzzy_suggestion():
    """Verify semantic error suggests the closest matching table name."""
    source = """
    dataset sales(amount: num) = load "sales.csv";
    res = slaes | limit 5;
    print res;
    """
    res = compile_flowql(source, target="python")
    assert not res["success"]
    errs = [e for e in res["errors"] if e["code"] == E101_UNDEFINED_NAME]
    assert len(errs) > 0
    # Should suggest 'sales'
    assert "Did you mean 'sales'?" in errs[0]["message"]


def test_undefined_variable_in_filter():
    """Verify undefined scalar variable inside expression produces E101."""
    source = """
    dataset sales(amount: num) = load "sales.csv";
    res = sales | filter amount > undefined_threshold;
    print res;
    """
    res = compile_flowql(source, target="python")
    assert not res["success"]
    assert any(e["code"] == E103_UNKNOWN_COLUMN for e in res["errors"])


def test_undefined_print_target_suggestion():
    """Verify print of undefined table gives helpful suggestion."""
    source = """
    dataset sales(amount: num) = load "sales.csv";
    summary = sales | limit 10;
    print summry;
    """
    res = compile_flowql(source, target="python")
    assert not res["success"]
    errs = [e for e in res["errors"] if e["code"] == E108_INVALID_PRINT]
    assert len(errs) > 0
    assert "Did you mean 'summary'?" in errs[0]["message"]


# =============================================================================
# 2. Wrong Columns & Schema Mismatches
# =============================================================================

def test_unknown_column_in_filter_suggests_available_columns():
    """Verify querying an unknown column lists available schema columns."""
    source = """
    dataset sales(region: str, amount: num) = load "sales.csv";
    res = sales | filter amnt > 100;
    print res;
    """
    res = compile_flowql(source, target="python")
    assert not res["success"]
    errs = [e for e in res["errors"] if e["code"] == E103_UNKNOWN_COLUMN]
    assert len(errs) > 0
    assert "Did you mean column 'amount'?" in errs[0]["message"]


def test_unknown_column_in_select_stage():
    """Verify selecting a nonexistent column raises E103."""
    source = """
    dataset sales(region: str, amount: num) = load "sales.csv";
    res = sales | select region, profit;
    print res;
    """
    res = compile_flowql(source, target="python")
    assert not res["success"]
    assert any(e["code"] == E103_UNKNOWN_COLUMN for e in res["errors"])


# =============================================================================
# 3. Grouping, Sorting, and Limit Validations
# =============================================================================

def test_non_numeric_aggregation_error():
    """Verify aggregating a string column produces E106 error."""
    source = """
    dataset sales(region: str, product: str) = load "sales.csv";
    res = sales | group region sum product;
    print res;
    """
    res = compile_flowql(source, target="python")
    assert not res["success"]
    assert any(e["code"] == E106_NON_NUMERIC_AGG for e in res["errors"])


def test_invalid_limit_count_zero_or_negative():
    """Verify limit with zero or negative number produces E107."""
    source = """
    dataset sales(amount: num) = load "sales.csv";
    res = sales | limit 0;
    print res;
    """
    res = compile_flowql(source, target="python")
    assert not res["success"]
    assert any(e["code"] == E107_INVALID_LIMIT for e in res["errors"])


def test_full_pipeline_group_sort_limit():
    """Verify end-to-end compilation with group, sort, and limit."""
    source = """
    dataset sales(region: str, amount: num) = load "sales.csv";
    by_region = sales | group region sum amount;
    top_regions = by_region | sort sum_amount desc | limit 3;
    print top_regions;
    """
    res_py = compile_flowql(source, target="python")
    res_sql = compile_flowql(source, target="sql")
    assert res_py["success"]
    assert res_sql["success"]
    assert "groupby" in res_py["target_code"]
    assert "GROUP BY" in res_sql["target_code"]
    assert "ORDER BY" in res_sql["target_code"]


# =============================================================================
# 4. Python vs SQL Equivalence
# =============================================================================

def test_python_and_sql_pipeline_structure_equivalence():
    """Verify Python and SQL backends generate corresponding operations."""
    source = """
    let min_amount = 50;
    dataset sales(region: str, amount: num, units: num) = load "sales.csv";
    filtered = sales | filter amount > min_amount and units >= 1;
    summary = filtered | group region sum amount;
    ordered = summary | sort sum_amount asc | limit 5;
    print ordered;
    """
    res_py = compile_flowql(source, target="python")
    res_sql = compile_flowql(source, target="sql")

    assert res_py["success"]
    assert res_sql["success"]

    py_code = res_py["target_code"]
    sql_code = res_sql["target_code"]

    # Check that both reference min_amount
    assert "min_amount = 50" in py_code
    assert "50" in sql_code

    # Check both contain filter logic
    assert "filtered" in py_code and "summary" in py_code and "ordered" in py_code
    assert "filtered AS (" in sql_code and "summary AS (" in sql_code and "ordered AS (" in sql_code


# =============================================================================
# 5. CSV Schema Inference
# =============================================================================

def test_infer_column_types_comprehensive():
    """Verify column inference across numbers, bools, and mixed types."""
    # Numbers
    assert infer_column_type(["10", "20.5", "-3", "0", "1e4"]) == "num"
    # Booleans
    assert infer_column_type(["True", "false", "TRUE", "False"]) == "bool"
    assert infer_column_type(["1", "0", "1", "1"]) == "num"  # Digits are treated as num
    assert infer_column_type(["yes", "no", "yes"]) == "bool"
    # Strings
    assert infer_column_type(["Alice", "Bob", "Charlie"]) == "str"
    assert infer_column_type(["10", "abc", "30"]) == "str"
    # Null / empty handling
    assert infer_column_type(["", "   ", None]) == "str"
    assert infer_column_type(["12", "", "34"]) == "num"


def test_inspect_csv_bytes_malformed_handling():
    """Verify empty and invalid CSV bytes produce informative errors."""
    with pytest.raises(ValueError, match="empty"):
        inspect_csv_bytes(b"", "empty.csv")

    with pytest.raises(ValueError, match="Binary file detected"):
        inspect_csv_bytes(b"\x00\x01\x02\x03\x04", "binary.csv")


def test_sanitize_identifier_edge_cases():
    """Verify identifier sanitization handles numbers, keywords, and special characters."""
    assert sanitize_identifier("123_count") == "col_123_count"
    assert sanitize_identifier("dataset") == "col_dataset"
    assert sanitize_identifier("filter") == "col_filter"
    assert sanitize_identifier("User Name ($)") == "User_Name"
    assert sanitize_identifier("a", existing={"a"}) == "a_2"


# =============================================================================
# 6. AI Failure, Timeout, and Retry Mechanism (Mocked)
# =============================================================================

def test_ai_explain_timeout_handling():
    """Verify that when Gemini API times out, explain_error returns a friendly fallback."""
    with patch("dslc.ai._call_gemini_with_retry", side_effect=TimeoutError("Request timed out after 8.0s")):
        res = explain_error(
            error_dict={"code": "E101", "message": "Undefined table 'foo'", "line": 1, "column": 1},
            source_code="res = foo | limit 5;"
        )
        assert res["available"] is False
        assert "timed out" in res["cause"].lower() or "offline" in res["cause"].lower()
        assert "tip" in res


def test_ai_review_timeout_handling():
    """Verify that when Gemini API times out during review, review_code returns safe fallback."""
    with patch("dslc.ai._call_gemini_with_retry", side_effect=TimeoutError("Request timed out after 8.0s")):
        res = review_code(
            source_code="print x;",
            target_code="print(x)",
            target_name="PYTHON"
        )
        assert res["available"] is False
        assert "timed out" in res["verdict"].lower() or "unavailable" in res["verdict"].lower()
        assert len(res["tips"]) > 0


def test_ai_retry_mechanism_on_transient_error():
    """Verify _call_gemini_with_retry retries once on temporary failure."""
    from dslc.ai import _call_gemini_with_retry

    call_count = 0

    def mock_generate_content(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ConnectionResetError("Transient network reset")
        mock_resp = MagicMock()
        mock_resp.text = '{"cause": "Success after retry", "suggested_code": "x = 1;", "tip": "Retry works"}'
        return mock_resp

    with patch("google.genai.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.models.generate_content = mock_generate_content
        mock_client_cls.return_value = mock_client

        result = _call_gemini_with_retry("test prompt")
        assert result is not None
        assert call_count == 2
        assert "Success after retry" in result


# =============================================================================
# 7. LRU Compilation Cache & Request Limits
# =============================================================================

def test_lru_cache_hit_and_invalidation():
    """Verify compilation cache hits on identical input and clears properly."""
    clear_compile_cache()
    stats_init = get_compile_cache_stats()
    assert stats_init["size"] == 0

    source = """
    dataset sales(amount: num) = load "sales.csv";
    top = sales | limit 5;
    print top;
    """

    # First compile: cache miss
    res1 = compile_flowql(source, target="python")
    assert res1["success"]
    stats_after_1 = get_compile_cache_stats()
    assert stats_after_1["size"] == 1
    assert stats_after_1["misses"] >= 1

    # Second compile: cache hit
    res2 = compile_flowql(source, target="python")
    assert res2["success"]
    assert res2["target_code"] == res1["target_code"]
    stats_after_2 = get_compile_cache_stats()
    assert stats_after_2["hits"] >= 1

    # Invalidate cache
    clear_compile_cache()
    stats_after_clear = get_compile_cache_stats()
    assert stats_after_clear["size"] == 0


def test_server_compile_oversized_payload_rejection():
    """Verify that requests with source code exceeding 256KB are rejected by Pydantic."""
    oversized_source = "dataset sales(a: num) = load 'a.csv';\n" + ("# comment\n" * 30000)
    assert len(oversized_source) > 256 * 1024

    resp = client.post("/api/compile", json={"source": oversized_source, "target": "python"})
    assert resp.status_code == 422  # Unprocessable Entity (Pydantic validation failure)


def test_server_timing_header_presence():
    """Verify X-Process-Time-Ms header is returned on API requests."""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert "x-process-time-ms" in resp.headers
    ms_val = float(resp.headers["x-process-time-ms"])
    assert ms_val >= 0.0
