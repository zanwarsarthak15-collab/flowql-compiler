# Project Spec: FlowQL, an AI-Assisted Mini Compiler for a Data-Pipeline DSL

**Course:** Compiler Design, B.Tech CS, Semester 5 (B2)
**Team:** Sarthak Zanwar, Meghshyam Pawar, Jash Panchal
**Timeline:** 5 days
**Cost constraint:** Zero. Open-source tools and the free Gemini API tier only.

---

## 0. Instructions for the AI agent (read first)

You are building this project end to end in this workspace. Follow these rules:

1. **Plan first.** Before writing code, produce a short plan that follows the milestones in Section 11. Then build milestone by milestone.
2. **Deterministic core first.** The lexer, parser, semantic analyzer, and code generators must work with no network and no API key. The AI layer is an optional enhancement that fails gracefully (Section 8).
3. **Never hard-code secrets.** Read `GEMINI_API_KEY` from the environment or a `.env` file. Create `.env.example` and add `.env` to `.gitignore`.
4. **Use a virtual environment** (`venv/`) and keep `requirements.txt` up to date.
5. **Write tests as you go** (`pytest`). Do not move to the next milestone while the current one's tests fail.
6. **Keep it readable.** This is a student project that will be explained in a viva. Prefer clear, commented code over clever code. Each compiler phase lives in its own module.
7. **Ask before** installing anything outside `requirements.txt` or adding features outside this spec.
8. **Check current docs** for the Gemini SDK (`google-genai`) and for model names before writing the AI client. Do not rely on memory for API signatures.

---

## 1. Executive summary

FlowQL is a small domain-specific language for describing data-processing pipelines over tabular (CSV) data: load a table, filter rows, select columns, group and aggregate, sort, and limit. The compiler translates FlowQL programs into **Python (pandas)** or **SQL**.

The compiler has two tiers:

- **Deterministic tier:** lexer, parser, AST, semantic analysis, intermediate representation (IR), and code generation.
- **AI tier (Google Gemini):** explains errors in plain English, suggests fixes, proposes pipeline optimizations, and reviews the generated target code.

## 2. Objectives

1. Define a precise context-free grammar (CFG) and token set for FlowQL.
2. Implement a lexer and parser with **PLY** (Python Lex-Yacc) that builds an AST.
3. Implement semantic analysis with a symbol table and schema propagation.
4. Generate target code for two backends: Python/pandas and SQL.
5. Integrate Gemini for error diagnosis, optimization suggestions, and target-code review.
6. Ship a CLI, a test suite, sample programs, and documentation.

**Non-goals:** a full programming language (no loops, functions, or user-defined types), joins, a GUI beyond the optional stretch goal, and paid services.

## 3. Language overview

### 3.1 Example program

```
dataset sales(region: str, product: str, amount: num, units: num) = load "sales.csv";

let threshold = 100;

top_regions = sales
    | filter amount > threshold and units >= 2
    | select region, amount
    | group region sum amount
    | sort sum_amount desc
    | limit 5;

print top_regions;
```

### 3.2 Types

`num` (integer or float), `str`, `bool`.

### 3.3 Keywords

`dataset load let print filter select group sort asc desc limit and or not true false sum avg min max count`

### 3.4 Comments

`# comment to end of line`

## 4. Lexical specification (tokens)

| Token | Pattern / lexeme |
|---|---|
| `ID` | `[A-Za-z_][A-Za-z0-9_]*` (not a keyword) |
| `NUMBER` | `[0-9]+(\.[0-9]+)?` |
| `STRING` | `"` ... `"` (no newlines inside) |
| Keywords | See 3.3. Each keyword is its own token type. |
| Operators | `+ - * / % == != < <= > >= =` |
| Delimiters | `( ) , ; : \|` |
| Skipped | whitespace, newlines (track line numbers), comments |

Lexical errors: illegal character, unterminated string. Both must report line and column.

## 5. Grammar (EBNF)

```
program       := statement*
statement     := dataset_decl | let_stmt | assign_stmt | print_stmt

dataset_decl  := "dataset" ID "(" column_list ")" "=" "load" STRING ";"
column_list   := column ("," column)*
column        := ID ":" type
type          := "num" | "str" | "bool"

let_stmt      := "let" ID "=" expr ";"
assign_stmt   := ID "=" pipeline ";"
print_stmt    := "print" ID ";"

pipeline      := ID ( "|" stage )*
stage         := "filter" expr
               | "select" ID ("," ID)*
               | "group" ID agg ID
               | "sort" ID [ "asc" | "desc" ]
               | "limit" NUMBER
agg           := "sum" | "avg" | "min" | "max" | "count"

expr          := or_expr
or_expr       := and_expr ( "or" and_expr )*
and_expr      := not_expr ( "and" not_expr )*
not_expr      := "not" not_expr | comparison
comparison    := arith ( ("==" | "!=" | "<" | "<=" | ">" | ">=") arith )?
arith         := term ( ("+" | "-") term )*
term          := factor ( ("*" | "/" | "%") factor )*
factor        := NUMBER | STRING | "true" | "false" | ID | "(" expr ")" | "-" factor
```

Operator precedence, high to low: unary `-`, `* / %`, `+ -`, comparisons, `not`, `and`, `or`. Resolve conflicts with PLY `precedence` where useful, and document any remaining shift/reduce conflicts.

## 6. Semantic analysis

Build a **symbol table** with two kinds of entries:

- **Variables** (from `let`): name and type.
- **Tables** (from `dataset` and pipeline assignments): name and schema, where schema is an ordered map of `column: type`.

**Schema propagation through pipeline stages:**

| Stage | Resulting schema |
|---|---|
| `filter` | Unchanged. The expression must be of type `bool`. |
| `select a, b` | Only the listed columns, in the listed order. |
| `group k agg c` | `{k: type_of_k, <agg>_<c>: num}`, e.g. `sum_amount`. `count` yields `count_<c>`. |
| `sort c` | Unchanged. `c` must exist in the current schema. |
| `limit n` | Unchanged. `n` must be a positive integer. |

**Semantic checks and error codes:**

| Code | Check |
|---|---|
| E101 | Use of an undefined variable or table |
| E102 | Redeclaration of a name |
| E103 | Unknown column for the current schema |
| E104 | Type mismatch in an expression (e.g. `str > num`, `and` on non-bool) |
| E105 | `filter` expression is not boolean |
| E106 | `sum` or `avg` on a non-numeric column |
| E107 | `limit` value is not a positive integer |
| E108 | `print` of an undefined or non-table name |

**Syntax and lexical error codes:** E001 illegal character, E002 unterminated string, E010 unexpected token, E011 unexpected end of input.

Every error object carries: `code`, `message`, `line`, `column`, and the source line text. The compiler should collect multiple semantic errors in one run, and for syntax errors should recover at the next `;` where practical.

## 7. Intermediate representation and code generation

### 7.1 IR

After semantic analysis, lower the AST to a simple linear **IR**: one step per statement or pipeline stage. Make it a plain dataclass list that can be printed and JSON-serialised (`--emit ir`). Example step: `{op: "filter", input: "sales", output: "t1", predicate: "..."}`.

### 7.2 Optimizer (deterministic, small)

Implement at least these passes on the IR:

1. **Constant folding** (`2 * 50` becomes `100`).
2. **Filter merging** (consecutive `filter` stages become one `and`).
3. **Predicate pushdown** (a `filter` that only uses columns present before a `select` or `group` moves earlier).

### 7.3 Backends

- **Python backend:** emits a runnable script using `pandas`. Example: `df = pd.read_csv("sales.csv")`, then boolean masks, `groupby().agg()`, `sort_values()`, `head()`. Include a comment mapping each block back to its FlowQL stage.
- **SQL backend:** emits ANSI-style SQL using one CTE per pipeline stage, ending with a final `SELECT`. Quote string literals correctly. Treat the dataset name as the table name.

Both backends must produce equivalent results for the sample programs (verify the Python output against the SQL output on a small SQLite database in tests).

## 8. AI tier (Google Gemini)

### 8.1 Setup

- SDK: `google-genai`. Free key from Google AI Studio. Key from `GEMINI_API_KEY`.
- Model name is configurable via `GEMINI_MODEL` in `.env`. Look up a current fast/free-tier model name in the official docs rather than assuming one.
- All AI calls go through one module (`dslc/ai/client.py`) with a timeout, a retry with backoff for rate limits, and a try/except wrapper.

### 8.2 Features (each is a separate function)

| Function | Input | Output |
|---|---|---|
| `explain_error` | Error object, the source, the grammar summary | Plain-English root cause, a corrected snippet, and a one-line tip |
| `suggest_optimizations` | The IR (JSON) | Up to 3 human-readable suggestions with a reason each |
| `review_target_code` | FlowQL source, generated code, target name | A verdict (OK or issues found) and any problems or improvements |

### 8.3 Rules

- The AI tier is **advisory only**. It never changes compiler output silently.
- Prompts must ask for a **strict JSON response** where structured output is needed. Parse defensively and strip code fences.
- **Graceful fallback:** with no key, no network, or an API error, print the normal deterministic error and a note that AI hints are unavailable. The compiler must never crash because of the AI layer.
- Send only the minimum needed (the failing statement, error, and a grammar summary). Never send the API key or unrelated files.
- Provide a `--no-ai` flag, and cache AI responses on disk (keyed by a hash of the prompt) to save quota during testing.
- Tests must **mock** the AI client. No test may hit the network.

## 9. Command-line interface

```
python -m dslc compile examples/valid/top_regions.fql --target python
python -m dslc compile examples/valid/top_regions.fql --target sql --out out.sql
python -m dslc compile examples/invalid/bad_column.fql --ai
python -m dslc compile prog.fql --emit tokens|ast|ir
python -m dslc check prog.fql            # syntax and semantic check only
```

Flags: `--target {python,sql}`, `--emit {tokens,ast,ir}`, `--ai / --no-ai`, `--optimize / --no-optimize`, `--out FILE`, `--verbose`.
Output should be readable, with colour optional. Exit code 0 on success, 1 on compile errors.

`--emit ast` should print an indented tree. This is useful for the demo and the viva.

## 10. Project structure

```
flowql/
├── README.md
├── requirements.txt          # ply, google-genai, python-dotenv, pytest, pandas
├── .env.example
├── .gitignore
├── dslc/
│   ├── __main__.py           # CLI entry
│   ├── lexer.py              # PLY lex
│   ├── parser.py             # PLY yacc, builds AST
│   ├── ast_nodes.py          # dataclasses
│   ├── errors.py             # error classes and codes
│   ├── semantic.py           # symbol table, schema propagation, checks
│   ├── ir.py                 # IR dataclasses, AST to IR lowering
│   ├── optimizer.py          # constant folding, filter merge, pushdown
│   ├── backends/
│   │   ├── python_gen.py
│   │   └── sql_gen.py
│   └── ai/
│       ├── client.py         # Gemini wrapper, retry, cache, fallback
│       └── prompts.py        # prompt templates
├── examples/
│   ├── data/sales.csv        # small sample dataset
│   ├── valid/                # 5 valid programs
│   └── invalid/              # 1 program per error code family
├── tests/
│   ├── test_lexer.py
│   ├── test_parser.py
│   ├── test_semantic.py
│   ├── test_optimizer.py
│   ├── test_backends.py      # includes SQLite equivalence check
│   └── test_ai_mocked.py
└── docs/
    ├── grammar.md
    └── report.md             # for submission (see Section 12)
```

## 11. Milestones (5 days)

| Day | Goal | Done when |
|---|---|---|
| 1 | Setup, lexer, parser, AST, `--emit tokens/ast` | All valid examples parse. Syntax errors give line and column. Lexer and parser tests pass. |
| 2 | Semantic analysis and error reporting | All E101 to E108 cases are detected with correct locations. Multiple errors are reported in one run. |
| 3 | IR, optimizer, Python backend | Valid examples compile to runnable pandas scripts that give correct output on `sales.csv`. |
| 4 | SQL backend, SQLite equivalence tests, Gemini tier | SQL results match Python results. The three AI functions work with a real key and fall back correctly without one. |
| 5 | Polish: README, docs, demo script, edge cases, final test run | `pytest` is green. Fresh-clone setup works from the README alone. |

**Stretch (only if Day 5 is finished early):** a small Streamlit web UI with a code editor, a target selector, and an AI-explanation panel.

## 12. Deliverables

1. Working source code, as in Section 10.
2. `README.md` with setup steps, usage examples, and an architecture diagram (a Mermaid diagram of the pipeline is fine).
3. `docs/grammar.md` listing tokens, the EBNF grammar, and the precedence table.
4. At least 5 valid and 8 invalid example programs.
5. A test suite that runs offline with `pytest`.
6. `docs/report.md` covering: problem statement, language design, compiler phases, AI integration, testing, limitations, and future work.

## 13. Acceptance criteria

- [ ] `pip install -r requirements.txt` then `pytest` passes on a clean machine, with no API key set.
- [ ] Every valid example compiles to both Python and SQL, and the results match.
- [ ] Every invalid example produces the expected error code, line, and column.
- [ ] With a valid key, `--ai` produces a clear explanation for at least 3 different error types.
- [ ] With no key or no network, `--ai` degrades gracefully and the program does not crash.
- [ ] No secrets are committed. `.env` is git-ignored.
- [ ] Each compiler phase can be demonstrated separately (`--emit tokens`, `--emit ast`, `--emit ir`).

## 14. Sample test cases (starter set)

**Valid:** the example in 3.1, plus a filter-only pipeline, a select-then-sort pipeline, a `count` aggregation, and a program with arithmetic in `let`.

**Invalid:**

| Program snippet | Expected |
|---|---|
| `x = sales \| filter amount > ;` | E010 unexpected token |
| `print "abc;` | E002 unterminated string |
| `x = sales2 \| limit 3;` (undeclared) | E101 |
| `x = sales \| select price;` | E103 unknown column |
| `x = sales \| filter region > 5;` | E104 type mismatch |
| `x = sales \| filter amount + 1;` | E105 non-boolean filter |
| `x = sales \| group region sum product;` | E106 sum on a string column |
| `x = sales \| limit 0;` | E107 |

## 15. Tech stack summary

Python 3.10+, PLY, pandas, SQLite (for tests, built into Python), `google-genai`, `python-dotenv`, pytest. All free and open source.
