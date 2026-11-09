"""Evaluator for the route conditions the compiler emits, without ``eval()``.

A condition is a small boolean expression over slot values, for example
``am__ok == 'yes' and len(am__slots) > 0``. The expression is parsed to a syntax
tree and only the node types listed here are executed. Anything else (attribute
access, subscripts, lambdas, comprehensions, calls to other functions) raises
``UnsafeExpressionError`` instead of running.
"""

from __future__ import annotations

import ast
import operator
from collections.abc import Callable, Mapping
from typing import Any

__all__ = ["UnsafeExpressionError", "safe_eval"]


class UnsafeExpressionError(ValueError):
    """Raised when an expression uses syntax outside the allowed subset."""


_COMPARE_OPS: dict[type[ast.cmpop], Callable[[Any, Any], bool]] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
    ast.In: lambda left, right: left in right,
    ast.NotIn: lambda left, right: left not in right,
}


def safe_eval(
    expression: str,
    names: Mapping[str, Any],
    functions: Mapping[str, Callable[..., Any]],
) -> Any:
    """Evaluate ``expression`` using only a fixed subset of Python syntax.

    Allowed: ``and``/``or``/``not``, comparisons (including ``is``, ``in``),
    literals, list/tuple/set displays, bare names, and calls to the functions in
    ``functions`` with positional arguments. ``and``/``or`` short-circuit.

    Args:
        expression: Condition text, as stored in ``graph.json``.
        names: Values for the bare names the expression may read.
        functions: Callables the expression may call, by name.

    Returns:
        The value of the expression.

    Raises:
        UnsafeExpressionError: The expression uses syntax outside the subset.
        NameError: The expression reads a name that is not in ``names``.
        SyntaxError: The expression is not valid Python.
    """
    tree = ast.parse(expression, mode="eval")
    return _eval(tree.body, names, functions)


def _eval(node: ast.AST, names: Mapping[str, Any], functions: Mapping[str, Callable[..., Any]]) -> Any:
    """Evaluate one syntax-tree node.

    Args:
        node: Node to evaluate.
        names: Values for bare names.
        functions: Callables the expression may call.

    Returns:
        The node's value.

    Raises:
        UnsafeExpressionError: The node type is not allowed.
        NameError: A bare name is missing from ``names``.
    """
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id not in names:
            raise NameError(node.id)
        return names[node.id]
    if isinstance(node, ast.BoolOp):
        is_and = isinstance(node.op, ast.And)
        result: Any = is_and
        for operand in node.values:
            result = _eval(operand, names, functions)
            if bool(result) != is_and:
                return result
        return result
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not _eval(node.operand, names, functions)
    if isinstance(node, ast.Compare):
        left = _eval(node.left, names, functions)
        for op, comparator in zip(node.ops, node.comparators, strict=True):
            compare = _COMPARE_OPS.get(type(op))
            if compare is None:
                raise UnsafeExpressionError(f"operator {type(op).__name__} is not allowed")
            right = _eval(comparator, names, functions)
            if not compare(left, right):
                return False
            left = right
        return True
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        items = [_eval(item, names, functions) for item in node.elts]
        return {ast.List: list, ast.Tuple: tuple, ast.Set: set}[type(node)](items)
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in functions or node.keywords:
            raise UnsafeExpressionError("only calls to allowed functions with positional args are permitted")
        args = [_eval(arg, names, functions) for arg in node.args]
        return functions[node.func.id](*args)
    raise UnsafeExpressionError(f"{type(node).__name__} is not allowed in a condition")
