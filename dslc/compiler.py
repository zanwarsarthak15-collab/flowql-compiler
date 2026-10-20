"""
FlowQL Compiler Driver.

Unifies all phases:
Lexer -> Parser -> Semantic Analysis -> IR Lowering -> Optimization -> Code Generation
"""
import copy
import threading
from collections import OrderedDict
from typing import Dict, Any, List, Optional, Tuple

from dslc.lexer import FlowQLLexer, tokenize_for_view
from dslc.parser import FlowQLParser
from dslc.semantic import SemanticAnalyzer
from dslc.ir import IRGenerator
from dslc.optimizer import optimize_ir
from dslc.backends.python_gen import PythonGenerator
from dslc.backends.sql_gen import SQLGenerator
from dslc.errors import CompileError

# Reusable shared parser instance (constructed once)
_shared_parser = FlowQLParser()

# Thread-safe bounded LRU compilation cache (max 100 items)
MAX_CACHE_SIZE = 100
_COMPILE_CACHE: OrderedDict = OrderedDict()
_CACHE_LOCK = threading.Lock()
_CACHE_HITS = 0
_CACHE_MISSES = 0


def clear_compile_cache() -> None:
    """Clears the compilation cache (useful for testing cache invalidation)."""
    global _CACHE_HITS, _CACHE_MISSES
    with _CACHE_LOCK:
        _COMPILE_CACHE.clear()
        _CACHE_HITS = 0
        _CACHE_MISSES = 0


def get_compile_cache_stats() -> Dict[str, int]:
    """Returns hit/miss stats and current size of the compilation cache."""
    with _CACHE_LOCK:
        return {
            "size": len(_COMPILE_CACHE),
            "hits": _CACHE_HITS,
            "misses": _CACHE_MISSES,
            "max_size": MAX_CACHE_SIZE,
        }


def compile_flowql(
    source: str,
    target: str = "python",
    optimize: bool = True,
    upload_id: Optional[str] = None,
    file_mappings: Optional[Dict[str, str]] = None,
    csv_schemas: Optional[Dict[str, List[str]]] = None,
    upload_manager: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Compiles FlowQL source code to target representation (python or sql).
    Returns complete compilation artifacts and any errors encountered.
    Supports optional upload_id and file_mappings for resolving uploaded CSV datasets.
    Backed by a bounded thread-safe LRU cache (100 items).
    """
    global _CACHE_HITS, _CACHE_MISSES

    target = target.lower()

    # Resolve CSV schema from upload_manager if provided
    resolved_csv_schemas = dict(csv_schemas or {})
    uploaded_dataset_info = None
    if upload_manager and upload_id:
        upload_meta = upload_manager.get_upload(upload_id)
        if upload_meta:
            cols = [c["name"] for c in upload_meta["columns"]] + [c["original_name"] for c in upload_meta["columns"]]
            resolved_csv_schemas[upload_meta["dataset_name"]] = cols
            resolved_csv_schemas[upload_meta["filename"]] = cols
            uploaded_dataset_info = {
                "upload_id": upload_meta["upload_id"],
                "filename": upload_meta["filename"],
                "dataset_name": upload_meta["dataset_name"],
                "columns": upload_meta["columns"],
            }

    # Build cache key: (source, target, optimize, upload_id, sorted_schemas)
    schema_key = tuple(sorted((k, tuple(v)) for k, v in resolved_csv_schemas.items())) if resolved_csv_schemas else None
    cache_key = (source, target, optimize, upload_id, schema_key)

    # Check cache
    with _CACHE_LOCK:
        if cache_key in _COMPILE_CACHE:
            _CACHE_HITS += 1
            _COMPILE_CACHE.move_to_end(cache_key)
            cached_result = copy.deepcopy(_COMPILE_CACHE[cache_key])
            cached_result["cache_hit"] = True
            return cached_result
        _CACHE_MISSES += 1

    result: Dict[str, Any] = {
        "success": False,
        "tokens": [],
        "ast": None,
        "ast_tree": "",
        "ir": [],
        "target": target,
        "target_code": "",
        "generated_code": "",
        "errors": [],
        "optimizations": [],
        "uploaded_dataset": uploaded_dataset_info,
        "cache_hit": False,
    }

    # 1. Lexical Analysis
    tokens_view, lex_errors = tokenize_for_view(source)
    result["tokens"] = tokens_view

    # 2. Syntactic Analysis (reuses compiled PLY parser and avoids duplicate token scan)
    ast, parse_errors = _shared_parser.parse(source, lex_errors=lex_errors)

    all_syntax_errors = lex_errors + parse_errors
    if all_syntax_errors:
        result["errors"] = [e.to_dict() for e in all_syntax_errors]
        return result

    if ast is None:
        result["errors"] = [{"code": "E011", "message": "Failed to parse program", "line": 1, "column": 1}]
        return result

    result["ast"] = ast.to_dict()
    result["ast_tree"] = ast.to_tree_str()

    # 3. Semantic Analysis with CSV Schema Validation
    semantic = SemanticAnalyzer(source_code=source, csv_schemas=resolved_csv_schemas)
    semantic_errors = semantic.analyze(ast)

    if semantic_errors:
        result["errors"] = [e.to_dict() for e in semantic_errors]
        return result

    # 4. IR Generation
    ir_gen = IRGenerator()
    ir_steps = ir_gen.lower(ast)

    # 5. Optimization
    opt_notes = []
    if optimize:
        ir_steps, opt_notes = optimize_ir(ir_steps)
    result["optimizations"] = opt_notes
    result["ir"] = [s.to_dict() for s in ir_steps]

    # 6. Target Code Generation
    if target == "sql":
        sql_gen = SQLGenerator()
        code = sql_gen.generate(ir_steps)
    else:
        py_gen = PythonGenerator()
        code = py_gen.generate(ir_steps)

    result["target_code"] = code
    result["generated_code"] = code
    result["success"] = True

    # Save to bounded LRU cache
    with _CACHE_LOCK:
        _COMPILE_CACHE[cache_key] = copy.deepcopy(result)
        if len(_COMPILE_CACHE) > MAX_CACHE_SIZE:
            _COMPILE_CACHE.popitem(last=False)

    return result

