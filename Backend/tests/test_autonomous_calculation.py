"""Executable calculation contracts used by ordinary chat."""

import pytest

from Backend.chat_modules.autonomous_calculation import calculate_math


def test_quadratic_uses_signed_coefficients_from_the_original_expression():
    result = calculate_math({"task": "quadratic", "expression": "y=x²-4x+3"})
    assert result["coefficients"] == {"a": "1", "b": "-4", "c": "3"}
    assert result["real_roots"] == ["1", "3"]
    assert result["vertex"] == {"x": "2", "y": "-1"}
    assert result["factor_pair"] == {"numbers": ["-1", "-3"], "sum": "-4", "product": "3"}


def test_general_math_code_can_run_a_bounded_sum_and_functions():
    result = calculate_math({"task": "code", "code": (
        "total = Fraction(0, 1)\n"
        "for k in range(1, 6):\n"
        "    total += Fraction(1, k*k)\n"
        "result = total"
    )})
    assert result["result"] == "5269/3600"
    assert result["exact"] is True
    assert calculate_math({"task": "code", "code": "result = math.sqrt(81) + math.factorial(4)"})["result"] == 33.0


@pytest.mark.parametrize("code", [
    "import os\nresult = 1",
    "result = open('secret.txt').read()",
    "result = __import__('os')",
    "while True:\n    pass",
    "result = (1).__class__",
    "for k in range(1000000):\n    result = k",
])
def test_math_code_rejects_unsafe_or_unbounded_programs(code):
    with pytest.raises(ValueError):
        calculate_math({"task": "code", "code": code})


def test_arithmetic_and_unsupported_expression_are_explicit():
    assert calculate_math({"task": "evaluate", "expression": "2*(3+4)^2"})["value"] == "98"
    with pytest.raises(ValueError, match="degree two"):
        calculate_math({"task": "quadratic", "expression": "x^3+1"})
