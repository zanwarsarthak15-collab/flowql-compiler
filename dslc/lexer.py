"""
FlowQL Lexical Analyzer (Lexer).

Implemented using PLY (Python Lex-Yacc).
Converts source code text into a stream of typed tokens with exact line
and column information, and captures lexical errors (E001, E002).
"""
import ply.lex as lex
from typing import List, Tuple, Optional
from dslc.errors import CompileError, E001_ILLEGAL_CHAR, E002_UNTERMINATED_STRING


# Reserved keywords mapped to token type
reserved = {
    'dataset': 'DATASET',
    'load': 'LOAD',
    'let': 'LET',
    'print': 'PRINT',
    'filter': 'FILTER',
    'select': 'SELECT',
    'group': 'GROUP',
    'sort': 'SORT',
    'asc': 'ASC',
    'desc': 'DESC',
    'limit': 'LIMIT',
    'and': 'AND',
    'or': 'OR',
    'not': 'NOT',
    'true': 'TRUE',
    'false': 'FALSE',
    'sum': 'SUM',
    'avg': 'AVG',
    'min': 'MIN',
    'max': 'MAX',
    'count': 'COUNT',
    'num': 'TYPE_NUM',
    'str': 'TYPE_STR',
    'bool': 'TYPE_BOOL',
}

tokens = list(reserved.values()) + [
    'ID',
    'NUMBER',
    'STRING',
    # Operators
    'PLUS',
    'MINUS',
    'TIMES',
    'DIVIDE',
    'MODULO',
    'EQ',
    'NEQ',
    'LE',
    'GE',
    'LT',
    'GT',
    'ASSIGN',
    'PIPE',
    # Delimiters
    'LPAREN',
    'RPAREN',
    'COMMA',
    'SEMICOLON',
    'COLON',
]

# Simple regex rules for operators and delimiters
t_EQ = r'=='
t_NEQ = r'!='
t_LE = r'<='
t_GE = r'>='
t_LT = r'<'
t_GT = r'>'
t_ASSIGN = r'='
t_PIPE = r'\|'
t_PLUS = r'\+'
t_MINUS = r'-'
t_TIMES = r'\*'
t_DIVIDE = r'/'
t_MODULO = r'%'
t_LPAREN = r'\('
t_RPAREN = r'\)'
t_COMMA = r','
t_SEMICOLON = r';'
t_COLON = r':'

# Ignored characters: spaces and tabs
t_ignore = ' \t\r'


def find_column(input_text: str, token) -> int:
    """Calculate 1-indexed column number of token in input_text."""
    line_start = input_text.rfind('\n', 0, token.lexpos)
    if line_start < 0:
        return token.lexpos + 1
    return token.lexpos - line_start


def get_line_text(input_text: str, lineno: int) -> str:
    """Retrieve text of line number lineno."""
    lines = input_text.splitlines()
    if 1 <= lineno <= len(lines):
        return lines[lineno - 1]
    return ""


# Comments: '#' to end of line
def t_COMMENT(t):
    r'\#.*'
    pass


# Newlines
def t_newline(t):
    r'\n+'
    t.lexer.lineno += len(t.value)


# Properly terminated string literal
def t_STRING(t):
    r'"([^"\\\n]|\\.)*"'
    raw = t.value[1:-1]
    # Decode basic escape characters
    try:
        t.value = raw.encode('utf-8').decode('unicode_escape')
    except Exception:
        t.value = raw
    return t


# Unterminated string literal (starts with " but newline/EOF before closing ")
def t_UNTERMINATED_STRING(t):
    r'"([^"\\\n]|\\.)*'
    col = find_column(t.lexer.lexdata, t)
    line_text = get_line_text(t.lexer.lexdata, t.lexer.lineno)
    t.lexer.errors.append(CompileError(
        code=E002_UNTERMINATED_STRING,
        message="Unterminated string literal",
        line=t.lexer.lineno,
        column=col,
        source_line=line_text
    ))
    # Do not return a token so parser isn't fed a bad string token


# Numeric literals: integers or floats
def t_NUMBER(t):
    r'\d+(\.\d+)?'
    if '.' in t.value:
        t.value = float(t.value)
    else:
        t.value = int(t.value)
    return t


# Identifiers and keywords
def t_ID(t):
    r'[A-Za-z_][A-Za-z0-9_]*'
    t.type = reserved.get(t.value, 'ID')
    return t


# Lexer error handling for illegal characters
def t_error(t):
    col = find_column(t.lexer.lexdata, t)
    line_text = get_line_text(t.lexer.lexdata, t.lexer.lineno)
    char = t.value[0]
    t.lexer.errors.append(CompileError(
        code=E001_ILLEGAL_CHAR,
        message=f"Illegal character '{char}'",
        line=t.lexer.lineno,
        column=col,
        source_line=line_text
    ))
    t.lexer.skip(1)


# Master lexer compiled once at module load
_master_lexer = lex.lex(debug=False)


class FlowQLLexer:
    """Wrapper around PLY lexer managing error accumulation and column tracking."""

    def __init__(self):
        self.lexer = _master_lexer.clone()
        self.lexer.errors = []

    def tokenize(self, source: str) -> Tuple[List[lex.LexToken], List[CompileError]]:
        """
        Tokenizes the source code string.
        Returns a tuple of (token_list, error_list).
        Each token has .column attached.
        """
        self.lexer.lineno = 1
        self.lexer.errors = []
        self.lexer.input(source)

        token_list = []
        while True:
            tok = self.lexer.token()
            if not tok:
                break
            tok.column = find_column(source, tok)
            token_list.append(tok)

        return token_list, list(self.lexer.errors)


def tokenize_for_view(source: str) -> Tuple[List[dict], List[CompileError]]:
    """Helper for web UI / demo to get JSON-ready list of tokens."""
    lexer_instance = FlowQLLexer()
    tokens, errors = lexer_instance.tokenize(source)
    view_tokens = [
        {
            "type": tok.type,
            "value": str(tok.value),
            "line": tok.lineno,
            "column": tok.column
        }
        for tok in tokens
    ]
    return view_tokens, errors
