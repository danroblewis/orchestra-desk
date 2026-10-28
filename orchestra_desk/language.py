"""The condition language's two small parts: a comparison (``holds = "<= 86400"``) and an
arithmetic expression over named readings (``expr = "stuck / max(total, 1)"``).

An expression is numbers, the names of its readings, ``+ - * / %``, parentheses, unary minus and
the functions ``min``, ``max`` and ``abs``. Nothing else parses: no attributes, no other calls, no
comparisons, no strings. It is parsed once with Python's ``ast`` and evaluated by walking the
tree, never by ``eval``."""

from __future__ import annotations

import ast
import math
import operator
import re
from dataclasses import dataclass

_COMPARE = re.compile(r"^\s*(<=|>=|==|!=|<|>)\s*(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*$")
_OPS = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge, "==": operator.eq, "!=": operator.ne}
_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Mod: operator.mod}
_FUNCS = {"min": min, "max": max, "abs": abs}


class LanguageError(ValueError):
    pass


@dataclass(frozen=True)
class Comparison:
    op: str
    bound: float

    def __call__(self, value: float) -> bool:
        return _OPS[self.op](value, self.bound)

    def __str__(self) -> str:
        return f"{self.op} {self.bound:g}"


def comparison(text: object) -> Comparison:
    """``"<= 86400"``: an operator (``< <= > >= == !=``) and a number."""
    m = _COMPARE.match(text) if isinstance(text, str) else None
    if not m:
        raise LanguageError(f"holds must be an operator and a number, like \"<= 86400\", not {text!r}")
    return Comparison(m.group(1), float(m.group(2)))


@dataclass(frozen=True)
class Expression:
    text: str
    tree: ast.Expression
    names: frozenset[str]

    def __call__(self, values: dict[str, float]) -> float:
        """The expression's value. Raises ``ArithmeticError`` (division by zero, overflow) or
        ``LanguageError`` for a result that is not a finite number."""
        v = _eval(self.tree.body, values)
        if not math.isfinite(v):
            raise LanguageError(f"{self.text} is not a finite number ({v})")
        return v


def expression(text: object) -> Expression:
    if not isinstance(text, str) or not text.strip():
        raise LanguageError("expr must be a non-empty string")
    try:
        tree = ast.parse(text.strip(), mode="eval")
    except SyntaxError as e:
        raise LanguageError(f"expr {text!r} does not parse: {e.msg}") from None
    names: set[str] = set()
    for node in ast.walk(tree):
        _allowed(node, text, names)
    return Expression(text.strip(), tree, frozenset(names))


def _allowed(node: ast.AST, text: str, names: set[str]) -> None:
    if isinstance(node, ast.Expression | ast.Load | ast.UAdd | ast.USub) or type(node) in _BIN:
        return
    if isinstance(node, ast.BinOp):
        if type(node.op) not in _BIN:
            raise LanguageError(f"expr {text!r}: only + - * / % are allowed")
        return
    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, ast.UAdd | ast.USub):
            raise LanguageError(f"expr {text!r}: only unary + and - are allowed")
        return
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, int | float):
            raise LanguageError(f"expr {text!r}: only numbers are allowed as constants")
        return
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS or node.keywords or not node.args:
            raise LanguageError(f"expr {text!r}: the only functions are min, max and abs")
        if node.func.id == "abs" and len(node.args) != 1:
            raise LanguageError(f"expr {text!r}: abs takes one argument")
        return
    if isinstance(node, ast.Name):
        if node.id not in _FUNCS:
            names.add(node.id)
        return
    raise LanguageError(f"expr {text!r}: {type(node).__name__} is not allowed (numbers, names, + - * / %, min, max, abs)")


def _eval(node: ast.AST, values: dict[str, float]) -> float:
    if isinstance(node, ast.Constant):
        return float(node.value)
    if isinstance(node, ast.Name):
        return float(values[node.id])
    if isinstance(node, ast.UnaryOp):
        v = _eval(node.operand, values)
        return -v if isinstance(node.op, ast.USub) else v
    if isinstance(node, ast.BinOp):
        return float(_BIN[type(node.op)](_eval(node.left, values), _eval(node.right, values)))
    if isinstance(node, ast.Call):
        return float(_FUNCS[node.func.id](*(_eval(a, values) for a in node.args)))
    raise LanguageError(f"cannot evaluate {type(node).__name__}")       # parse refused it already
