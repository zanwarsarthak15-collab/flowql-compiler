# FlowQL Grammar Specification

FlowQL is a domain-specific language (DSL) for tabular data processing pipelines.

---

## 1. Lexical Structure

### 1.1 Keywords
`dataset`, `load`, `let`, `print`, `filter`, `select`, `group`, `sort`, `asc`, `desc`, `limit`, `and`, `or`, `not`, `true`, `false`, `sum`, `avg`, `min`, `max`, `count`, `num`, `str`, `bool`

### 1.2 Operators & Delimiters
- **Arithmetic:** `+`, `-`, `*`, `/`, `%`
- **Comparison:** `==`, `!=`, `<`, `<=`, `>`, `>=`
- **Assignment:** `=`
- **Pipeline:** `|`
- **Delimiters:** `(`, `)`, `,`, `;`, `:`

### 1.3 Literals & Identifiers
- **IDENTIFIER (`ID`):** `[A-Za-z_][A-Za-z0-9_]*` (excluding keywords)
- **NUMBER:** `[0-9]+(\.[0-9]+)?` (parsed as `int` or `float`)
- **STRING:** `"([^"\n\r\\]|\\.)*"`
- **BOOLEAN:** `true` | `false`
- **COMMENTS:** `#.*` (ignored)
- **WHITESPACE:** `[ \t\r\n]+` (ignored, newlines tracked for line counts)

---

## 2. Context-Free Grammar (EBNF)

```ebnf
program         ::= statement*

statement       ::= dataset_decl
                  | let_stmt
                  | pipeline_assign
                  | print_stmt

dataset_decl    ::= "dataset" ID "(" column_list ")" "=" "load" STRING ";"
column_list     ::= column ("," column)*
column          ::= ID ":" type
type            ::= "num" | "str" | "bool"

let_stmt        ::= "let" ID "=" expr ";"
pipeline_assign ::= ID "=" pipeline ";"
print_stmt      ::= "print" ID ";"

pipeline        ::= ID ( "|" stage )*
stage           ::= "filter" expr
                  | "select" ID ("," ID)*
                  | "group" ID agg ID
                  | "sort" ID [ "asc" | "desc" ]
                  | "limit" NUMBER

agg             ::= "sum" | "avg" | "min" | "max" | "count"

expr            ::= or_expr
or_expr         ::= and_expr ( "or" and_expr )*
and_expr        ::= not_expr ( "and" not_expr )*
not_expr        ::= "not" not_expr | comparison
comparison      ::= arith ( ("==" | "!=" | "<" | "<=" | ">" | ">=") arith )?
arith           ::= term ( ("+" | "-") term )*
term            ::= factor ( ("*" | "/" | "%") factor )*
factor          ::= NUMBER
                  | STRING
                  | "true"
                  | "false"
                  | ID
                  | "(" expr ")"
                  | "-" factor
```

---

## 3. Operator Precedence & Associativity

Highest precedence to lowest:

| Operator | Associativity | Description |
|---|---|---|
| `-` (unary) | Right | Unary negation |
| `*`, `/`, `%` | Left | Multiplicative |
| `+`, `-` | Left | Additive |
| `==`, `!=`, `<`, `<=`, `>`, `>=` | None / Non-associative | Comparison |
| `not` | Right | Logical NOT |
| `and` | Left | Logical AND |
| `or` | Left | Logical OR |

---

## 4. Error Recovery Strategy

During syntactic parsing with PLY:
- If a syntax error is encountered (`p_error(p)`), the compiler registers an `E010` (unexpected token) or `E011` (unexpected EOF) error with exact line and column.
- The parser utilizes error token synchronization rules `p_statement_error` discarding tokens up to the terminating semicolon `;`.
- This enables cascading syntax error collection across multiple statements in a single run.
