"""
Tests for FlowQL Lexer.
"""
import pytest
from dslc.lexer import FlowQLLexer, tokenize_for_view
from dslc.errors import E001_ILLEGAL_CHAR, E002_UNTERMINATED_STRING


def test_lexer_valid_tokens():
    source = 'dataset sales(region: str, amount: num) = load "data.csv";'
    lexer = FlowQLLexer()
    tokens, errors = lexer.tokenize(source)

    assert len(errors) == 0
    token_types = [t.type for t in tokens]
    assert token_types == [
        'DATASET', 'ID', 'LPAREN', 'ID', 'COLON', 'TYPE_STR', 'COMMA',
        'ID', 'COLON', 'TYPE_NUM', 'RPAREN', 'ASSIGN', 'LOAD', 'STRING', 'SEMICOLON'
    ]
    # Check values and columns
    assert tokens[0].value == 'dataset'
    assert tokens[0].lineno == 1
    assert tokens[0].column == 1


def test_lexer_comments_and_whitespace():
    source = """# Full line comment
let x = 42; # Inline comment
# Trailing comment
"""
    tokens, errors = tokenize_for_view(source)
    assert len(errors) == 0
    types = [t["type"] for t in tokens]
    assert types == ['LET', 'ID', 'ASSIGN', 'NUMBER', 'SEMICOLON']
    assert tokens[0]["line"] == 2


def test_lexer_operators_and_keywords():
    source = "filter a > 10 and b == true or c != false;"
    tokens, errors = tokenize_for_view(source)
    assert len(errors) == 0
    types = [t["type"] for t in tokens]
    assert "FILTER" in types
    assert "GT" in types
    assert "AND" in types
    assert "EQ" in types
    assert "TRUE" in types
    assert "OR" in types
    assert "NEQ" in types
    assert "FALSE" in types


def test_lexer_illegal_character():
    source = "let x = 100 @ 20;"
    tokens, errors = tokenize_for_view(source)
    assert len(errors) == 1
    err = errors[0]
    assert err.code == E001_ILLEGAL_CHAR
    assert "@" in err.message
    assert err.line == 1
    assert err.column == 13


def test_lexer_unterminated_string():
    source = 'let path = "unclosed_string;\nlet y = 1;'
    tokens, errors = tokenize_for_view(source)
    assert len(errors) >= 1
    err = errors[0]
    assert err.code == E002_UNTERMINATED_STRING
    assert err.line == 1
