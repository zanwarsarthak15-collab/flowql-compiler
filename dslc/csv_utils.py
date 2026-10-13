"""
FlowQL CSV Utilities & Schema Detection Engine.

Provides secure CSV parsing, robust schema inference (num, str, bool),
column identifier sanitization for the FlowQL grammar, and upload management.
"""
import csv
import io
import os
import re
import uuid
import time
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional, Set

# Maximum file size allowed for uploads (10 MB)
MAX_UPLOAD_SIZE = 10 * 1024 * 1024

# FlowQL reserved keywords that cannot be used directly as column or dataset identifiers
RESERVED_KEYWORDS: Set[str] = {
    "dataset", "load", "let", "print", "filter", "select", "group",
    "sort", "asc", "desc", "limit", "and", "or", "not", "true", "false",
    "sum", "avg", "min", "max", "count", "num", "str", "bool"
}

# Boolean literal strings for detection
BOOL_TRUE_STRINGS = {"true", "1", "yes", "t"}
BOOL_FALSE_STRINGS = {"false", "0", "no", "f"}
ALL_BOOL_STRINGS = BOOL_TRUE_STRINGS | BOOL_FALSE_STRINGS


def sanitize_identifier(raw_name: str, index: int = 1, existing: Optional[Set[str]] = None) -> str:
    """
    Sanitizes arbitrary CSV column headers into valid FlowQL identifiers:
    - Replaces whitespace and non-alphanumeric characters with underscores
    - Strips leading and trailing underscores
    - Prefixes with 'col_' if the name starts with a digit or is empty
    - Prefixes with 'col_' if the name conflicts with FlowQL keywords
    - Deduplicates against existing identifiers in the same schema
    """
    if existing is None:
        existing = set()

    clean = raw_name.strip()
    # Replace non-alphanumeric characters with underscores
    clean = re.sub(r'[^a-zA-Z0-9_]', '_', clean)
    # Collapse multiple consecutive underscores
    clean = re.sub(r'_+', '_', clean)
    clean = clean.strip('_')

    # If empty or started with non-letters
    if not clean:
        clean = f"col_{index}"
    elif clean[0].isdigit():
        clean = f"col_{clean}"

    # If lowercase matches a reserved keyword
    if clean.lower() in RESERVED_KEYWORDS:
        clean = f"col_{clean}"

    # Deduplicate against existing identifiers
    base = clean
    count = 1
    while clean in existing:
        count += 1
        clean = f"{base}_{count}"

    return clean


def sanitize_dataset_name(filename: str) -> str:
    """Derives a clean, valid FlowQL dataset identifier from a filename."""
    stem = Path(filename).stem
    clean = sanitize_identifier(stem, index=1)
    return clean


def infer_column_type(values: List[str]) -> str:
    """
    Infers the FlowQL column type ('num', 'bool', 'str') from a list of string values.
    Empty strings / nulls are ignored during type testing.
    If all non-empty values can be parsed as numbers -> 'num'.
    If all non-empty values are recognized boolean literals -> 'bool'.
    Otherwise -> 'str'.
    """
    non_empty = [v.strip() for v in values if v is not None and v.strip() != ""]
    if not non_empty:
        return "str"  # Safe default fallback for empty columns

    # 1. Check numeric
    is_numeric = True
    for v in non_empty:
        # Check standard int or float
        try:
            float(v)
        except ValueError:
            is_numeric = False
            break

    if is_numeric:
        return "num"

    # 2. Check boolean
    is_bool = True
    for v in non_empty:
        if v.lower() not in ALL_BOOL_STRINGS:
            is_bool = False
            break

    if is_bool:
        return "bool"

    # 3. Fallback to string
    return "str"


def inspect_csv_bytes(
    file_bytes: bytes,
    filename: str,
    preview_limit: int = 10
) -> Dict[str, Any]:
    """
    Safely inspects and parses raw CSV bytes.
    Validates CSV format, infers columns and data types, and extracts preview rows.
    """
    if len(file_bytes) == 0:
        raise ValueError("Uploaded file is empty (0 bytes).")

    if len(file_bytes) > MAX_UPLOAD_SIZE:
        raise ValueError(f"File size exceeds maximum allowed limit of {MAX_UPLOAD_SIZE // (1024 * 1024)} MB.")

    # Detect encoding: try utf-8 with fallback to latin-1
    try:
        text = file_bytes.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = file_bytes.decode("latin-1")
        except UnicodeDecodeError:
            raise ValueError("File content is not valid text or UTF-8/Latin-1 encoded CSV.")

    # Check for binary or null bytes
    if "\x00" in text[:4096]:
        raise ValueError("Binary file detected. Only plain-text CSV files are supported.")

    # Read CSV
    stream = io.StringIO(text)
    try:
        # Sniff delimiter if possible, default to comma
        sample = text[:8192]
        delimiter = ","
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
            delimiter = dialect.delimiter
        except Exception:
            delimiter = ","

        reader = csv.reader(stream, delimiter=delimiter)
        raw_header = None
        rows = []
        for row in reader:
            if not row:
                continue
            if raw_header is None:
                raw_header = row
            else:
                rows.append(row)
    except Exception as e:
        raise ValueError(f"Malformed CSV: could not parse table structure ({str(e)}).")

    if not raw_header:
        raise ValueError("CSV file must contain at least a header row.")

    # Deduplicate and sanitize column names
    existing_identifiers: Set[str] = set()
    columns_info: List[Dict[str, Any]] = []
    col_values_map: Dict[int, List[str]] = {i: [] for i in range(len(raw_header))}

    for i, col_raw in enumerate(raw_header):
        ident = sanitize_identifier(col_raw, index=i + 1, existing=existing_identifiers)
        existing_identifiers.add(ident)
        columns_info.append({
            "name": ident,
            "original_name": col_raw.strip(),
            "index": i,
            "type": "str"  # Will update below
        })

    # Collect column values for type inference (scan up to 200 rows for speed and accuracy)
    scan_limit = min(len(rows), 200)
    for row in rows[:scan_limit]:
        for i in range(len(raw_header)):
            val = row[i] if i < len(row) else ""
            col_values_map[i].append(val)

    # Infer types
    for i, col in enumerate(columns_info):
        col["type"] = infer_column_type(col_values_map[i])

    # Build preview rows (up to preview_limit)
    preview_rows: List[Dict[str, Any]] = []
    for row in rows[:preview_limit]:
        row_dict = {}
        for i, col in enumerate(columns_info):
            raw_val = row[i] if i < len(row) else ""
            row_dict[col["name"]] = raw_val
        preview_rows.append(row_dict)

    # Suggest declaration
    ds_name = sanitize_dataset_name(filename)
    safe_filename = Path(filename).name
    schema_parts = [f"{col['name']}: {col['type']}" for col in columns_info]
    suggested_decl = f'dataset {ds_name}({", ".join(schema_parts)}) = load "{safe_filename}";'

    return {
        "filename": safe_filename,
        "dataset_name": ds_name,
        "file_size": len(file_bytes),
        "total_rows": len(rows),
        "columns": columns_info,
        "preview_rows": preview_rows,
        "suggested_declaration": suggested_decl,
        "delimiter": delimiter,
    }


class CSVUploadManager:
    """
    Manages persisted temporary CSV uploads in a safe, controlled directory.
    Prevents path traversal, filename collisions, and arbitrary filesystem access.
    """

    def __init__(self, base_dir: Optional[Path] = None):
        if base_dir is None:
            cand = Path(__file__).resolve().parent.parent / "data" / "uploads"
            try:
                cand.mkdir(parents=True, exist_ok=True)
                test_file = cand / ".write_test"
                test_file.touch()
                test_file.unlink()
                base_dir = cand
            except Exception:
                import tempfile
                base_dir = Path(tempfile.gettempdir()) / "flowql_uploads"
                base_dir.mkdir(parents=True, exist_ok=True)

        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.registry: Dict[str, Dict[str, Any]] = {}

    def save_upload(self, file_bytes: bytes, original_filename: str) -> Dict[str, Any]:
        """Saves a validated CSV upload and returns its metadata."""
        inspection = inspect_csv_bytes(file_bytes, original_filename)

        upload_id = str(uuid.uuid4())
        safe_filename = Path(original_filename).name
        # Secure unique filename on disk
        stored_filename = f"{upload_id}_{safe_filename}"
        target_path = self.base_dir / stored_filename

        with open(target_path, "wb") as f:
            f.write(file_bytes)

        metadata = {
            "upload_id": upload_id,
            "filename": safe_filename,
            "dataset_name": inspection["dataset_name"],
            "file_size": inspection["file_size"],
            "total_rows": inspection["total_rows"],
            "columns": inspection["columns"],
            "preview_rows": inspection["preview_rows"],
            "suggested_declaration": inspection["suggested_declaration"],
            "stored_path": str(target_path),
            "uploaded_at": time.time(),
        }

        self.registry[upload_id] = metadata
        return metadata

    def get_upload(self, upload_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves upload metadata by unique upload ID."""
        return self.registry.get(upload_id)

    def find_by_filename(self, filename: str) -> Optional[Dict[str, Any]]:
        """Finds the most recent upload matching the given filename."""
        safe_name = Path(filename).name
        matches = [m for m in self.registry.values() if m["filename"] == safe_name]
        if matches:
            # Sort by uploaded_at descending
            matches.sort(key=lambda m: m.get("uploaded_at", 0), reverse=True)
            return matches[0]
        return None

    def delete_upload(self, upload_id: str) -> bool:
        """Safely removes an uploaded file from disk and registry."""
        meta = self.registry.pop(upload_id, None)
        if not meta:
            return False

        path_str = meta.get("stored_path")
        if path_str:
            p = Path(path_str)
            if p.exists() and p.is_file():
                try:
                    p.unlink()
                except OSError:
                    pass
        return True

    def resolve_dataset_path(self, load_path: str, upload_id: Optional[str] = None) -> Optional[Path]:
        """
        Resolves a FlowQL load path to an actual file on disk:
        1. Checks upload_id if provided.
        2. Checks recent uploaded files matching filename.
        3. Checks data/ and examples/data/ for built-in datasets (e.g. sales.csv).
        4. Resolves direct relative paths if safe.
        """
        if upload_id and upload_id in self.registry:
            stored = Path(self.registry[upload_id]["stored_path"])
            if stored.exists():
                return stored

        # Check by filename in uploaded registry
        filename_only = Path(load_path).name
        upload_meta = self.find_by_filename(filename_only)
        if upload_meta:
            stored = Path(upload_meta["stored_path"])
            if stored.exists():
                return stored

        # Check project root data/ and examples/data/
        project_root = Path(__file__).resolve().parent.parent
        candidates = [
            project_root / load_path,
            project_root / "data" / filename_only,
            project_root / "examples" / "data" / filename_only,
            project_root / "data" / "uploads" / filename_only,
        ]
        for c in candidates:
            if c.exists() and c.is_file():
                return c

        return None
