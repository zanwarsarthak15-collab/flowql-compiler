"""
FlowQL Compiler Driver.

Unifies all phases:
Lexer -> Parser -> Semantic Analysis -> IR Lowering -> Optimization -> Code Generation
"""
from typing import Dict, Any, List, Optional
from dslc.lexer import FlowQLLexer, tokenize_for_view
from dslc.parser import FlowQLParser
from dslc.semantic import SemanticAnalyzer
from dslc.ir import IRGenerator
from dslc.optimizer import optimize_ir
from dslc.backends.python_gen import PythonGenerator
from dslc.backends.sql_gen import SQLGenerator
from dslc.errors import CompileError


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
    """
    target = target.lower()
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
        "uploaded_dataset": None,
    }

    # Resolve CSV schema from upload_manager if provided
    resolved_csv_schemas = dict(csv_schemas or {})
    if upload_manager and upload_id:
        upload_meta = upload_manager.get_upload(upload_id)
        if upload_meta:
            cols = [c["name"] for c in upload_meta["columns"]] + [c["original_name"] for c in upload_meta["columns"]]
            resolved_csv_schemas[upload_meta["dataset_name"]] = cols
            resolved_csv_schemas[upload_meta["filename"]] = cols
            result["uploaded_dataset"] = {
                "upload_id": upload_meta["upload_id"],
                "filename": upload_meta["filename"],
                "dataset_name": upload_meta["dataset_name"],
                "columns": upload_meta["columns"],
            }

    # 1. Lexical Analysis
    tokens_view, lex_errors = tokenize_for_view(source)
    result["tokens"] = tokens_view

    # 2. Syntactic Analysis
    parser = FlowQLParser()
    ast, parse_errors = parser.parse(source)

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
    return result
