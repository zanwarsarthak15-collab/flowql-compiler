# Project Report: FlowQL Compiler & AI Studio

**Course:** Compiler Design (B.Tech Computer Science, Semester 5)  
**Team Members:** Sarthak Zanwar, Meghshyam Pawar, Jash Panchal  
**Domain:** Domain-Specific Languages (DSL), Compilers, AI Integration  

---

## 1. Problem Statement & Motivation

Data engineers and analysts frequently write repetitive pipelines to filter, aggregate, and reshape tabular datasets. While SQL and Python (pandas) are industry standards, SQL queries often become difficult to maintain with deep nested subqueries, and Python scripts can be verbose and prone to dataframe syntax subtleties.

**FlowQL** was created as an elegant, clean, domain-specific language designed specifically for linear tabular data pipelines over CSV files. Furthermore, traditional compilers emit cryptic syntax or type error messages; FlowQL bridges traditional deterministic compiler theory with generative AI (Google Gemini) to deliver advisory, plain-English explanations and actionable fixes.

---

## 2. Language Design

FlowQL enforces a linear, pipeline-first programming model:

```flowql
dataset sales(region: str, product: str, amount: num, units: num) = load "data/sales.csv";
let threshold = 100;
top = sales
    | filter amount > threshold and units >= 2
    | select region, amount
    | group region sum amount
    | sort sum_amount desc
    | limit 5;
print top;
```

### 2.1 Types
- `num`: Numeric values (integers or floating-point numbers).
- `str`: String literals.
- `bool`: Boolean values (`true` or `false`).

### 2.2 Statements
1. **Dataset Declaration:** `dataset <name>(<schema>) = load "<path>";`
2. **Variable Assignment:** `let <var> = <expr>;`
3. **Pipeline Assignment:** `<target> = <source_table> | <stage_1> | <stage_2> ...;`
4. **Print Statement:** `print <table_name>;`

### 2.3 Pipeline Stages
- `filter <expr>`: Row filtering using boolean predicates.
- `select <col1>, <col2>`: Projection down to specified columns.
- `group <key_col> <agg_func> <agg_col>`: Aggregates (`sum`, `avg`, `min`, `max`, `count`) yielding `<key_col>` and `<agg>_<agg_col>`.
- `sort <col> [asc|desc]`: Deterministic sorting.
- `limit <n>`: Top-N record truncation.

---

## 3. Compiler Phases & Architecture

The FlowQL compiler follows traditional front-end, intermediate, and back-end separation:

```
[ FlowQL Source ]
        │
        ▼
   [ Lexer (PLY) ] ───────────► Tokens & Lexical Errors (E001, E002)
        │
        ▼
   [ Parser (PLY) ] ──────────► AST Dataclasses & Syntax Recovery (E010, E011)
        │
        ▼
[ Semantic Analyzer ] ────────► Symbol Tables, Schema Propagation, Diagnostics (E101 - E108)
        │
        ▼
   [ IR Lowering ] ───────────► Linear IRSteps Sequence
        │
        ▼
   [ Optimizer ] ─────────────► Constant Folding & Filter Merging
        │
        ├──────────────────────────┐
        ▼                          ▼
[ Python/pandas Generator ]   [ SQL CTE Generator ]
```

### Phase 1: Lexical Analysis (`dslc/lexer.py`)
- Implemented with **PLY (Python Lex-Yacc)**.
- Tokenizes identifiers, keywords, numbers, strings, and operators while maintaining line and column tracking (`lexpos`).
- Error codes:
  - `E001`: Illegal character encountered.
  - `E002`: Unterminated string literal.

### Phase 2: Syntactic Analysis (`dslc/parser.py`)
- Context-free grammar implemented with Shift-Reduce parsing in PLY.
- Formal operator precedence table resolves ambiguity (unary negation > multiplicative > additive > comparisons > logical `not` > `and` > `or`).
- Builds a structured AST of strongly-typed dataclasses.
- **Error Synchronization:** Recovers at the nearest `;` (`error SEMICOLON` rule) allowing the compiler to report multiple syntax errors across statements in a single run.

### Phase 3: Semantic Analysis (`dslc/semantic.py`)
- Maintains two distinct symbol tables:
  1. `variables`: Scalar let bindings with inferred types.
  2. `tables`: Data tables with ordered schemas (`column_name -> type`).
- Performs schema propagation through each pipeline stage.
- Validates constraints and emits error codes:
  - `E101`: Undefined variable or dataset.
  - `E102`: Redeclaration of existing identifier.
  - `E103`: Column not present in current schema.
  - `E104`: Expression type mismatch.
  - `E105`: Non-boolean condition in `filter`.
  - `E106`: Non-numeric column in `sum` or `avg`.
  - `E107`: Non-positive integer in `limit`.
  - `E108`: Printing undefined table or printing a scalar variable.

### Phase 4: Intermediate Representation (IR) (`dslc/ir.py`)
- Lowers AST into a linear list of `IRStep` dataclasses:
  `{step_id, op, input_ref, output_ref, details, comment}`.
- Simplifies multi-stage pipeline reasoning and makes optimization passes straightforward.

### Phase 5: Optimization (`dslc/optimizer.py`)
- **Constant Folding:** Compile-time reduction of constant expressions (e.g. `25 * 2 + 50` folds to `100`).
- **Filter Merging:** Combines consecutive `filter` operations into a single conjunctive predicate (`and`).

### Phase 6: Code Generation (`dslc/backends/`)
- **Python / pandas Target:** Generates clean, runnable Python scripts utilizing vectorized pandas operations (`df.groupby().agg()`, boolean indexing, `head()`).
- **SQL Target:** Emits standard ANSI SQL using Common Table Expressions (`WITH ... AS (...)`), where each CTE corresponds directly to a pipeline stage.
- Each block contains a header comment tying back to the original FlowQL step.

---

## 4. Google Gemini AI Integration (`dslc/ai.py`)

FlowQL incorporates an advisory LLM tier using the modern `google-genai` SDK:
- **`explain_error`**: Analyzes the error code, failing source line, and source context. Returns plain-English root causes and a concrete code fix.
- **`review_code`**: Reviews the FlowQL logic alongside the generated target code (Python or SQL) to provide verification verdicts and performance tips.
- **Zero-Failure Architecture:** The compiler remains 100% deterministic. If the API key is absent, offline, or rate-limited, friendly fallbacks are returned without halting compilation.
- Prompts enforce strict JSON schemas parsed defensively with regex fallbacks.

---

## 5. Web Studio (UI/UX)

Designed following Google's Material 3 design system:
- **Theme Support:** Clean, calm Google Blue palette with automatic and toggleable Light/Dark modes stored in `localStorage`.
- **Reactive Editing:** Real-time compilation debounced at 600ms, with `Ctrl+Enter` shortcut.
- **Gutter Markers & Underlines:** Red error indicators directly in the code editor, hovering shows the diagnostic message.
- **One-Click AI Fixes:** "Apply Fix" button automatically inserts Gemini's suggested fix into the editor.
- **Interactive Inspection:** Dedicated tabs for generated code, tokens table, AST tree/JSON, and visual IR cards.
- **Zero Build Step:** Plain HTML5, CSS3, and modern ES6 JavaScript served directly by FastAPI.

---

## 6. Testing & Validation

Comprehensive test suite built with `pytest`:
- `tests/test_lexer.py`: Token types, column offsets, comment stripping, E001/E002 errors.
- `tests/test_parser.py`: AST construction, operator precedence, syntax error recovery.
- `tests/test_semantic.py`: Symbol table tracking, schema propagation, E101–E108 error triggers.
- `tests/test_optimizer.py`: Constant evaluation and filter concatenation.
- `tests/test_backends.py`: Python/SQL syntax verification and **SQLite execution equivalence** testing comparing SQLite output to pandas DataFrame output.
- `tests/test_ai.py`: Mocked offline tests for fallback handling and JSON parsing.
- `tests/test_server.py`: FastAPI endpoints and static asset serving.

**Result:** 32 / 32 tests passing.

---

## 7. Viva Discussion Questions & Answers

1. **Why PLY over manual recursive descent?**  
   PLY provides formal LALR(1) shift-reduce parsing backed by Python generators, handling operator precedence and unambiguous parsing tables deterministically while supporting `error` token recovery.

2. **How does schema propagation work?**  
   Each statement takes an input table schema (column-to-type map). Stages mutate the schema deterministically (e.g., `select` filters columns; `group` drops unselected columns and introduces aggregated numeric outputs).

3. **Why use CTEs for SQL code generation?**  
   Common Table Expressions directly mirror the sequential stage-by-stage pipeline model, making generated SQL readable, easy to debug, and friendly to query optimizers.
