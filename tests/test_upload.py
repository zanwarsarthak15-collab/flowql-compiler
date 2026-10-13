"""
Comprehensive Tests for FlowQL CSV Upload, Schema Detection, and Compilation Workflow.
"""
import io
import sqlite3
import pytest
from pathlib import Path
import pandas as pd
from fastapi.testclient import TestClient

from server import app, upload_manager
from dslc.compiler import compile_flowql
from dslc.csv_utils import (
    inspect_csv_bytes,
    sanitize_identifier,
    infer_column_type,
    MAX_UPLOAD_SIZE,
)

client = TestClient(app)


def test_sanitize_identifier_rules():
    """Tests identifier sanitization rules for FlowQL grammar compatibility."""
    assert sanitize_identifier("Customer Name") == "Customer_Name"
    assert sanitize_identifier("1st_place") == "col_1st_place"
    assert sanitize_identifier("count") == "col_count"  # Reserved keyword
    assert sanitize_identifier("group") == "col_group"  # Reserved keyword
    assert sanitize_identifier("total-$ (USD)") == "total_USD"
    assert sanitize_identifier("   ") == "col_1"

    # Deduplication
    existing = {"score"}
    assert sanitize_identifier("score", existing=existing) == "score_2"


def test_infer_column_type_rules():
    """Tests type inference across numeric, boolean, string, and missing values."""
    assert infer_column_type(["10", "20", "30.5"]) == "num"
    assert infer_column_type(["true", "false", "TRUE"]) == "bool"
    assert infer_column_type(["yes", "no", "yes"]) == "bool"
    assert infer_column_type(["Alice", "Bob", "Charlie"]) == "str"
    assert infer_column_type(["10", "N/A", "20"]) == "str"  # Mixed text
    assert infer_column_type(["", "   ", None]) == "str"  # Empty fallback


def test_upload_csv_success():
    """Tests successful CSV upload and metadata extraction."""
    csv_content = b"student_name,score,passed\nAlice,95,true\nBob,72,false\nCharlie,88,true\n"
    response = client.post(
        "/api/upload-csv",
        files={"file": ("students.csv", io.BytesIO(csv_content), "text/csv")}
    )
    assert response.status_code == 200
    data = response.json()

    assert "upload_id" in data
    assert data["filename"] == "students.csv"
    assert data["dataset_name"] == "students"
    assert data["total_rows"] == 3
    assert len(data["columns"]) == 3

    # Check detected column types
    types = {c["name"]: c["type"] for c in data["columns"]}
    assert types["student_name"] == "str"
    assert types["score"] == "num"
    assert types["passed"] == "bool"

    # Check preview rows
    assert len(data["preview_rows"]) == 3
    assert data["preview_rows"][0]["student_name"] == "Alice"

    # Clean up
    client.delete(f"/api/upload-csv/{data['upload_id']}")


def test_upload_reject_non_csv():
    """Tests that non-CSV extensions are rejected with 400."""
    response = client.post(
        "/api/upload-csv",
        files={"file": ("malicious.exe", io.BytesIO(b"MZ..."), "application/octet-stream")}
    )
    assert response.status_code == 400
    assert "Only CSV files" in response.json()["detail"]


def test_upload_reject_empty_file():
    """Tests that an empty 0-byte file is rejected."""
    response = client.post(
        "/api/upload-csv",
        files={"file": ("empty.csv", io.BytesIO(b""), "text/csv")}
    )
    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()


def test_upload_reject_malformed_binary_file():
    """Tests that binary content disguised as a .csv is rejected."""
    binary_data = b"\x00\x01\x02\x03\x04\xff\xfe"
    response = client.post(
        "/api/upload-csv",
        files={"file": ("corrupt.csv", io.BytesIO(binary_data), "text/csv")}
    )
    assert response.status_code == 400
    assert "binary" in response.json()["detail"].lower() or "malformed" in response.json()["detail"].lower()


def test_upload_size_limit():
    """Tests that files exceeding 10 MB limit are rejected."""
    oversized = b"a,b\n" + (b"1,2\n" * ((MAX_UPLOAD_SIZE // 4) + 10))
    response = client.post(
        "/api/upload-csv",
        files={"file": ("large.csv", io.BytesIO(oversized), "text/csv")}
    )
    assert response.status_code == 400
    assert "exceeds" in response.json()["detail"].lower()


def test_upload_duplicate_filenames():
    """Tests that uploading multiple files with the same name yields unique upload IDs."""
    csv_1 = b"id,val\n1,10\n"
    csv_2 = b"id,val\n2,20\n"

    r1 = client.post("/api/upload-csv", files={"file": ("data.csv", io.BytesIO(csv_1), "text/csv")})
    r2 = client.post("/api/upload-csv", files={"file": ("data.csv", io.BytesIO(csv_2), "text/csv")})

    assert r1.status_code == 200
    assert r2.status_code == 200

    d1 = r1.json()
    d2 = r2.json()

    assert d1["upload_id"] != d2["upload_id"]

    # Clean up
    client.delete(f"/api/upload-csv/{d1['upload_id']}")
    client.delete(f"/api/upload-csv/{d2['upload_id']}")


def test_delete_upload_endpoint():
    """Tests deleting an uploaded CSV file."""
    csv_content = b"a,b\n1,2\n"
    r = client.post("/api/upload-csv", files={"file": ("temp.csv", io.BytesIO(csv_content), "text/csv")})
    upload_id = r.json()["upload_id"]

    del_res = client.delete(f"/api/upload-csv/{upload_id}")
    assert del_res.status_code == 200
    assert del_res.json()["success"] is True

    # Deleting again should return 404
    del_res_again = client.delete(f"/api/upload-csv/{upload_id}")
    assert del_res_again.status_code == 404


def test_flowql_compilation_with_uploaded_csv():
    """
    Tests end-to-end FlowQL compilation for Python and SQL targets
    using an uploaded CSV dataset.
    """
    csv_content = b"department,salary,active\nEngineering,120000,true\nMarketing,75000,true\nEngineering,135000,false\nSales,90000,true\n"
    r = client.post("/api/upload-csv", files={"file": ("employees.csv", io.BytesIO(csv_content), "text/csv")})
    assert r.status_code == 200
    meta = r.json()
    upload_id = meta["upload_id"]

    flowql_source = """
    dataset employees(department: str, salary: num, active: bool) = load "employees.csv";
    top_dept = employees
        | filter salary > 80000 and active == true
        | group department avg salary
        | sort avg_salary desc
        | limit 2;
    print top_dept;
    """

    # Compile Python
    py_res = client.post("/api/compile", json={
        "source": flowql_source,
        "target": "python",
        "optimize": True,
        "upload_id": upload_id
    })
    assert py_res.status_code == 200
    py_data = py_res.json()
    assert py_data["success"] is True
    assert 'pd.read_csv("employees.csv")' in py_data["target_code"]
    assert len(py_data["tokens"]) > 0
    assert len(py_data["ir"]) > 0

    # Compile SQL
    sql_res = client.post("/api/compile", json={
        "source": flowql_source,
        "target": "sql",
        "optimize": True,
        "upload_id": upload_id
    })
    assert sql_res.status_code == 200
    sql_data = sql_res.json()
    assert sql_data["success"] is True
    assert "WITH" in sql_data["target_code"]
    assert "AVG(salary) AS avg_salary" in sql_data["target_code"]

    # Clean up
    client.delete(f"/api/upload-csv/{upload_id}")


def test_python_and_sql_equivalence_on_uploaded_dataset():
    """
    Executes the generated Python code and generated SQL query (in SQLite)
    on an uploaded CSV and asserts that both outputs produce identical DataFrames.
    """
    csv_content = (
        b"region,product,amount,units\n"
        b"North,Laptop,1200,3\n"
        b"South,Mouse,25,10\n"
        b"East,Keyboard,80,5\n"
        b"West,Monitor,350,2\n"
        b"North,Keyboard,75,4\n"
        b"South,Laptop,1100,2\n"
    )
    r = client.post("/api/upload-csv", files={"file": ("custom_sales.csv", io.BytesIO(csv_content), "text/csv")})
    assert r.status_code == 200
    meta = r.json()
    upload_id = meta["upload_id"]

    # Obtain actual stored disk path from manager for execution
    stored_path = upload_manager.get_upload(upload_id)["stored_path"]
    stored_path_clean = stored_path.replace("\\", "/")

    # FlowQL source referencing the uploaded CSV
    source = f"""
    dataset custom_sales(region: str, product: str, amount: num, units: num) = load "{stored_path_clean}";
    top = custom_sales
        | filter amount > 50 and units >= 2
        | group region sum amount
        | sort sum_amount desc
        | limit 3;
    print top;
    """

    res_py = compile_flowql(source, target="python", upload_id=upload_id)
    res_sql = compile_flowql(source, target="sql", upload_id=upload_id)

    assert res_py["success"] is True
    assert res_sql["success"] is True

    # 1. Execute Python
    py_env = {}
    exec(res_py["target_code"], py_env)
    assert "top" in py_env
    py_df = py_env["top"]

    # 2. Execute SQL in SQLite
    conn = sqlite3.connect(":memory:")
    raw_df = pd.read_csv(stored_path)
    raw_df.to_sql("custom_sales", conn, index=False)

    clean_sql = "\n".join([line for line in res_sql["target_code"].splitlines() if not line.strip().startswith("--")])
    sql_df = pd.read_sql_query(clean_sql, conn)
    conn.close()

    # 3. Verify equivalence
    assert len(py_df) == len(sql_df)
    assert list(py_df.columns) == list(sql_df.columns)
    pd.testing.assert_frame_equal(py_df, sql_df, check_dtype=False)

    # Clean up
    client.delete(f"/api/upload-csv/{upload_id}")


def test_schema_mismatch_validation_against_uploaded_file():
    """
    Tests that declaring a column in FlowQL that does NOT exist in the uploaded CSV
    yields a diagnostic error (E109).
    """
    csv_content = b"name,score\nAlice,90\nBob,85\n"
    r = client.post("/api/upload-csv", files={"file": ("grades.csv", io.BytesIO(csv_content), "text/csv")})
    upload_id = r.json()["upload_id"]

    source = """
    dataset grades(name: str, non_existent_col: num) = load "grades.csv";
    res = grades | limit 2;
    print res;
    """

    res = compile_flowql(source, target="python", upload_id=upload_id, upload_manager=upload_manager)
    assert res["success"] is False
    assert len(res["errors"]) > 0
    assert any(e["code"] == "E109" for e in res["errors"])

    # Clean up
    client.delete(f"/api/upload-csv/{upload_id}")


def test_missing_upload_id_degrades_gracefully():
    """Tests compiling with non-existent upload_id succeeds if syntax is valid."""
    source = """
    dataset test(a: num, b: str) = load "test.csv";
    res = test | limit 1;
    print res;
    """
    res = compile_flowql(source, target="python", upload_id="non-existent-uuid-1234")
    assert res["success"] is True
    assert "pd.read_csv" in res["target_code"]
