"""
FlowQL Command-Line Interface (CLI).

Supports compiling FlowQL files to Python/pandas or SQL, checking syntax/semantics,
inspecting compilation stages (--emit tokens|ast|ir), and querying Google Gemini.
"""
import sys
import argparse
import json
from pathlib import Path

from dslc.compiler import compile_flowql
from dslc.ai import explain_error, review_code


def main():
    parser = argparse.ArgumentParser(
        prog="flowql",
        description="FlowQL Compiler: Mini DSL for Tabular Data Pipelines"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # compile subcommand
    compile_cmd = subparsers.add_parser("compile", help="Compile a FlowQL program")
    compile_cmd.add_argument("file", help="Path to .fql source file")
    compile_cmd.add_argument("--target", choices=["python", "sql"], default="python", help="Target language (default: python)")
    compile_cmd.add_argument("--emit", choices=["tokens", "ast", "ir", "code"], default="code", help="Stage to emit (default: code)")
    compile_cmd.add_argument("--optimize", dest="optimize", action="store_true", default=True, help="Enable optimizations")
    compile_cmd.add_argument("--no-optimize", dest="optimize", action="store_false", help="Disable optimizations")
    compile_cmd.add_argument("--ai", action="store_true", help="Request AI explanation for errors or review")
    compile_cmd.add_argument("--out", "-o", help="Write output to specified file")

    # check subcommand
    check_cmd = subparsers.add_parser("check", help="Verify syntax and semantics without code generation")
    check_cmd.add_argument("file", help="Path to .fql source file")
    check_cmd.add_argument("--emit", choices=["tokens", "ast", "ir"], default=None, help="Optionally emit tokens or AST")

    args = parser.parse_args()

    file_path = Path(args.file)
    if not file_path.exists():
        print(f"Error: File '{args.file}' does not exist.", file=sys.stderr)
        sys.exit(1)

    source = file_path.read_text(encoding="utf-8")

    if args.command == "check":
        res = compile_flowql(source, target="python", optimize=False)
        if res["errors"]:
            print(f"FAILED: Found {len(res['errors'])} error(s):", file=sys.stderr)
            for err in res["errors"]:
                print(f"  [{err['code']}] Line {err['line']}, Col {err['column']}: {err['message']}", file=sys.stderr)
                if err.get("source_line"):
                    print(f"    {err['source_line']}", file=sys.stderr)
            sys.exit(1)
        else:
            if args.emit == "tokens":
                print(json.dumps(res["tokens"], indent=2))
            elif args.emit == "ast":
                print(res["ast_tree"] or json.dumps(res["ast"], indent=2))
            elif args.emit == "ir":
                print(json.dumps(res["ir"], indent=2))
            else:
                print(f"PASSED: '{args.file}' passed all syntax and semantic checks.")
            sys.exit(0)

    elif args.command == "compile":
        res = compile_flowql(source, target=args.target, optimize=args.optimize)

        if res["errors"]:
            print(f"Compilation Failed with {len(res['errors'])} error(s):", file=sys.stderr)
            for err in res["errors"]:
                print(f"  [{err['code']}] Line {err['line']}, Col {err['column']}: {err['message']}", file=sys.stderr)
                if err.get("source_line"):
                    print(f"    {err['source_line']}", file=sys.stderr)

            if args.ai:
                print("\n[AI Advisory Error Diagnostic]:", file=sys.stderr)
                first_err = res["errors"][0]
                ai_exp = explain_error(first_err, source)
                if ai_exp.get("available"):
                    print(f"  Root Cause: {ai_exp.get('cause')}", file=sys.stderr)
                    if ai_exp.get("suggested_code"):
                        print(f"  Suggested Fix:\n{ai_exp.get('suggested_code')}", file=sys.stderr)
                    if ai_exp.get("tip"):
                        print(f"  Tip: {ai_exp.get('tip')}", file=sys.stderr)
                else:
                    print(f"  {ai_exp.get('cause')}", file=sys.stderr)

            sys.exit(1)

        # Success - emit requested artifact
        output_text = ""
        if args.emit == "tokens":
            output_text = json.dumps(res["tokens"], indent=2)
        elif args.emit == "ast":
            output_text = res["ast_tree"] or json.dumps(res["ast"], indent=2)
        elif args.emit == "ir":
            output_text = json.dumps(res["ir"], indent=2)
        else:
            output_text = res["target_code"]

        if args.out:
            Path(args.out).write_text(output_text, encoding="utf-8")
            print(f"Written output to {args.out}")
        else:
            print(output_text)

        if args.ai and args.emit == "code":
            print("\n" + "=" * 50)
            print("[Google Gemini Advisory Code Review]")
            print("=" * 50)
            rev = review_code(source, res["target_code"], args.target.capitalize())
            print(f"Verdict: {rev.get('verdict')}")
            for t in rev.get("tips", []):
                print(f" - {t}")

        sys.exit(0)


if __name__ == "__main__":
    main()
