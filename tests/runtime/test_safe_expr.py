"""Tests for the restricted condition evaluator."""

import pytest

from agent_runtime.runtime.safe_expr import UnsafeExpressionError, safe_eval

FUNCS = {"len": len}


def test_comparison_and_boolean_operators():
    names = {"a": "yes", "n": 3, "x": None}
    assert safe_eval("a == 'yes' and n >= 3", names, FUNCS) is True
    assert safe_eval("a == 'no' or x is None", names, FUNCS) is True
    assert safe_eval("x is not None", names, FUNCS) is False
    assert safe_eval("not (n < 2)", names, FUNCS) is True


def test_allowed_function_call():
    assert safe_eval("len(items) > 0", {"items": [1]}, FUNCS) is True


def test_and_short_circuits_before_failing_call():
    # len(None) would raise TypeError if evaluated.
    assert safe_eval("x is not None and len(x) > 0", {"x": None}, FUNCS) is False


def test_missing_name_raises_name_error():
    with pytest.raises(NameError):
        safe_eval("missing == 1", {}, FUNCS)


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('echo x')",
        "().__class__.__bases__",
        "open('f')",
        "len.__call__(a)",
        "a[0] == 1",
        "(lambda: 1)()",
        "[i for i in a]",
        "a + 1",
        "len(a, key=1)",
    ],
)
def test_disallowed_syntax_is_rejected(expression):
    with pytest.raises(UnsafeExpressionError):
        safe_eval(expression, {"a": [1]}, FUNCS)
