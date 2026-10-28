"""The condition language's two parts: comparisons and expressions, and what they refuse."""

import pytest

from orchestra_desk.language import LanguageError, comparison, expression


@pytest.mark.parametrize("text,value,expected", [
    ("<= 86400", 86400, True), ("< 1", 1, False), ("> -2.5", 0, True), (">= 1e3", 999, False),
    ("== 0", 0, True), ("!= 0", 0, False),
])
def test_comparisons(text, value, expected):
    assert comparison(text)(value) is expected


@pytest.mark.parametrize("text", ["86400", "<=", "<= one", "=< 3", "<= 3 4", 5, None])
def test_bad_comparisons_are_refused(text):
    with pytest.raises(LanguageError):
        comparison(text)


def test_expressions():
    e = expression("stuck / max(working, 1) * 100 - abs(-1) + 2 % 2")
    assert e.names == {"stuck", "working"}
    assert e({"stuck": 1, "working": 4}) == 24
    assert expression("-x")({"x": 2}) == -2
    with pytest.raises(ZeroDivisionError):
        expression("a / b")({"a": 1, "b": 0})


@pytest.mark.parametrize("text", [
    "__import__('os').system('true')", "a.b", "a[0]", "a if b else c", "a < b", "'text'", "open(a)",
    "lambda: 1", "a ** 2", "max()", "abs(a, b)", "min(a, key=b)", "True", "a and b", "",
])
def test_anything_else_is_refused(text):
    with pytest.raises(LanguageError):
        expression(text)
