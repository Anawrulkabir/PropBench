"""Safe formulas for worksheets, curve fitting and uncertainty budgets (README §2e).

A formula is a Python expression over named columns or quantities, e.g. ``nu * rho``, ``a * exp(-b / T) + c`` or
``eos("Dmass", T, p, fluid="R134a")``. It is parsed with ``ast`` and only a whitelist is allowed: numbers, names,
arithmetic (+ - * / ** %), comparisons, ``and``/``or``/``not``, conditional expressions and calls of the functions
below. No attribute access, no indexing, no lambdas, no imports: a formula can compute, nothing else. Evaluation
is vectorised with numpy.
"""

from __future__ import annotations

import ast
import math
from collections.abc import Callable, Mapping
from functools import lru_cache
from typing import Any

import numpy as np


class FormulaError(ValueError):
    """A formula is not valid or cannot be evaluated."""


def _eos(output: str, x: Any, y: Any, fluid: str = "", pair: str = "PT") -> np.ndarray:
    """Reference-EoS property (CoolProp) of ``fluid``: ``pair`` "PT" takes (T, p) as ``(x, y)``; "QT" (Q, T)."""
    from propbench.backends.coolprop import CoolPropBackend

    if not fluid:
        raise FormulaError("eos() needs fluid=..., e.g. eos('Dmass', T, p, fluid='R134a')")
    a, b = np.broadcast_arrays(np.asarray(x, dtype=float), np.asarray(y, dtype=float))
    pairs = {"PT": ("PT_INPUTS", b, a), "QT": ("QT_INPUTS", a, b), "DT": ("DmolarT_INPUTS", b, a)}
    if pair not in pairs:
        raise FormulaError(f"eos(): pair must be one of {sorted(pairs)}")
    name, v1, v2 = pairs[pair]
    batch = CoolPropBackend().properties(fluid, name, np.ravel(v1), np.ravel(v2), [output])
    return np.asarray(batch[output]).reshape(a.shape)


FUNCTIONS: dict[str, Callable[..., Any]] = {
    "exp": np.exp,
    "log": np.log,
    "ln": np.log,
    "log10": np.log10,
    "sqrt": np.sqrt,
    "abs": np.abs,
    "sin": np.sin,
    "cos": np.cos,
    "tan": np.tan,
    "arcsin": np.arcsin,
    "arccos": np.arccos,
    "arctan": np.arctan,
    "sinh": np.sinh,
    "cosh": np.cosh,
    "tanh": np.tanh,
    "minimum": np.minimum,
    "maximum": np.maximum,
    "where": np.where,
    "isfinite": np.isfinite,
    "eos": _eos,
}
CONSTANTS = {"pi": math.pi, "e": math.e, "R": 8.31446261815324, "NA": 6.02214076e23, "kB": 1.380649e-23}

_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod, ast.FloorDiv)
_ALLOWED = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.BoolOp,
    ast.Compare,
    ast.IfExp,
    ast.Call,
    ast.Name,
    ast.Load,
    ast.Constant,
    ast.keyword,
    ast.And,
    ast.Or,
    ast.Not,
    ast.USub,
    ast.UAdd,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    *_BINOPS,
)


@lru_cache(maxsize=512)
def parse(text: str) -> ast.Expression:
    if len(text) > 2000:
        raise FormulaError("formula is too long")
    try:
        tree = ast.parse(text.strip(), mode="eval")
    except SyntaxError as exc:
        raise FormulaError(f"invalid formula {text!r}: {exc.msg}") from None
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED):
            raise FormulaError(f"{type(node).__name__} is not allowed in a formula: {text!r}")
        if isinstance(node, ast.Call) and not (isinstance(node.func, ast.Name) and node.func.id in FUNCTIONS):
            raise FormulaError(f"unknown function in {text!r} (allowed: {', '.join(sorted(FUNCTIONS))})")
        if isinstance(node, ast.Constant) and not isinstance(node.value, int | float | str | bool):
            raise FormulaError(f"constant {node.value!r} is not allowed")
    return tree


def names(text: str) -> set[str]:
    """Variables a formula uses (function names and constants excluded)."""
    tree = parse(text)
    funcs = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} - funcs - set(CONSTANTS)


def evaluate(text: str, variables: Mapping[str, Any]) -> Any:
    """Value of the formula with ``variables`` (numbers or numpy arrays)."""
    tree = parse(text)
    missing = names(text) - set(variables)
    if missing:
        raise FormulaError(f"unknown name(s) {sorted(missing)} in {text!r}")
    return _eval(tree.body, {**CONSTANTS, **variables})


def compile_function(text: str, arguments: list[str]) -> Callable[..., Any]:
    """A Python function of ``arguments`` (positional, in order) computing the formula."""
    tree = parse(text)
    unknown = names(text) - set(arguments)
    if unknown:
        raise FormulaError(f"unknown name(s) {sorted(unknown)} in {text!r}")

    def f(*values: Any) -> Any:
        return _eval(tree.body, {**CONSTANTS, **dict(zip(arguments, values, strict=True))})

    return f


def _eval(node: ast.AST, env: Mapping[str, Any]) -> Any:
    with np.errstate(all="ignore"):
        return _ev(node, env)


def _ev(node: ast.AST, env: Mapping[str, Any]) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return env[node.id]
    if isinstance(node, ast.BinOp):
        a, b = _ev(node.left, env), _ev(node.right, env)
        op = node.op
        if isinstance(op, ast.Add):
            return a + b
        if isinstance(op, ast.Sub):
            return a - b
        if isinstance(op, ast.Mult):
            return a * b
        if isinstance(op, ast.Div):
            return np.true_divide(a, b)
        if isinstance(op, ast.Pow):
            return np.power(np.asarray(a, dtype=float), b)
        if isinstance(op, ast.Mod):
            return np.mod(a, b)
        return np.floor_divide(a, b)
    if isinstance(node, ast.UnaryOp):
        v = _ev(node.operand, env)
        if isinstance(node.op, ast.USub):
            return -v
        if isinstance(node.op, ast.UAdd):
            return +v
        return np.logical_not(v)
    if isinstance(node, ast.BoolOp):
        values = [_ev(v, env) for v in node.values]
        out = values[0]
        for v in values[1:]:
            out = np.logical_and(out, v) if isinstance(node.op, ast.And) else np.logical_or(out, v)
        return out
    if isinstance(node, ast.Compare):
        left = _ev(node.left, env)
        result: Any = True
        for op, comp in zip(node.ops, node.comparators, strict=True):
            right = _ev(comp, env)
            cmp = {
                ast.Eq: np.equal,
                ast.NotEq: np.not_equal,
                ast.Lt: np.less,
                ast.LtE: np.less_equal,
                ast.Gt: np.greater,
                ast.GtE: np.greater_equal,
            }[type(op)]
            result = np.logical_and(result, cmp(left, right))
            left = right
        return result
    if isinstance(node, ast.IfExp):
        return np.where(_ev(node.test, env), _ev(node.body, env), _ev(node.orelse, env))
    if isinstance(node, ast.Call):
        func = FUNCTIONS[node.func.id]  # type: ignore[attr-defined]
        args = [_ev(a, env) for a in node.args]
        kwargs = {k.arg: _ev(k.value, env) for k in node.keywords if k.arg}
        return func(*args, **kwargs)
    raise FormulaError(f"cannot evaluate {type(node).__name__}")  # pragma: no cover - parse() rejects it
