"""Bounded, deterministic arithmetic for the ordinary-chat Agent."""
from __future__ import annotations

import ast
from fractions import Fraction
import math
from math import isqrt, sqrt
import re


MAX_EXPRESSION_LENGTH = 160
MAX_AST_NODES = 60
MAX_ABSOLUTE_VALUE = 10**18
MAX_CODE_LENGTH = 2000
MAX_CODE_NODES = 180
MAX_CODE_STEPS = 10000
MAX_LOOP_ITEMS = 2000

SAFE_MATH_FUNCTIONS = {
    "sqrt": math.sqrt, "isqrt": math.isqrt,
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan,
    "log": math.log, "log10": math.log10, "exp": math.exp,
    "floor": math.floor, "ceil": math.ceil,
    "gcd": math.gcd, "factorial": math.factorial,
}


def _number(value: object) -> Fraction:
    if type(value) not in (int, float):
        raise ValueError("Only numeric constants are supported")
    if len(str(value)) > 32:
        raise ValueError("Numeric constant is too large")
    return Fraction(str(value))


def _bounded(poly: tuple[Fraction, Fraction, Fraction]) -> tuple[Fraction, Fraction, Fraction]:
    if any(abs(part.numerator) > MAX_ABSOLUTE_VALUE or part.denominator > MAX_ABSOLUTE_VALUE
           for part in poly):
        raise ValueError("Calculation exceeds the supported range")
    return poly


def _add(left, right):
    return _bounded(tuple(a + b for a, b in zip(left, right)))


def _multiply(left, right):
    result = [Fraction(0) for _ in range(5)]
    for i, a in enumerate(left):
        for j, b in enumerate(right):
            result[i + j] += a * b
    if any(result[3:]):
        raise ValueError("Polynomials above degree two are not supported")
    return _bounded(tuple(result[:3]))


def _polynomial(node: ast.AST) -> tuple[Fraction, Fraction, Fraction]:
    zero = Fraction(0)
    if isinstance(node, ast.Constant):
        return _bounded((_number(node.value), zero, zero))
    if isinstance(node, ast.Name) and node.id == "x":
        return (zero, Fraction(1), zero)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        operand = _polynomial(node.operand)
        return operand if isinstance(node.op, ast.UAdd) else _bounded(tuple(-part for part in operand))
    if isinstance(node, ast.BinOp):
        left, right = _polynomial(node.left), _polynomial(node.right)
        if isinstance(node.op, ast.Add):
            return _add(left, right)
        if isinstance(node.op, ast.Sub):
            return _add(left, tuple(-part for part in right))
        if isinstance(node.op, ast.Mult):
            return _multiply(left, right)
        if isinstance(node.op, ast.Div):
            if right[1] or right[2] or not right[0]:
                raise ValueError("Division requires a nonzero constant")
            return _bounded(tuple(part / right[0] for part in left))
        if isinstance(node.op, ast.Pow):
            if right[1] or right[2] or right[0].denominator != 1:
                raise ValueError("Exponent must be a nonnegative integer")
            exponent = int(right[0])
            if exponent < 0 or exponent > 12:
                raise ValueError("Exponent exceeds the supported range")
            if (left[1] or left[2]) and exponent > 2:
                raise ValueError("Polynomials above degree two are not supported")
            result = (Fraction(1), zero, zero)
            for _ in range(exponent):
                result = _multiply(result, left)
            return result
    raise ValueError("Unsupported mathematical expression")


def _parse(expression: str) -> tuple[str, tuple[Fraction, Fraction, Fraction]]:
    if not isinstance(expression, str) or not expression.strip() or len(expression) > MAX_EXPRESSION_LENGTH:
        raise ValueError("Provide a short mathematical expression")
    normalized = expression.strip().replace("−", "-").replace("×", "*").replace("÷", "/")
    normalized = re.sub(r"^(?:y|f\(x\))\s*=\s*", "", normalized, flags=re.I)
    normalized = normalized.replace("²", "**2").replace("³", "**3").replace("^", "**")
    normalized = re.sub(r"(?<=\d)(?=x|\()", "*", normalized, flags=re.I)
    normalized = re.sub(r"(?<=\))(?=x|\d|\()", "*", normalized, flags=re.I)
    try:
        tree = ast.parse(normalized, mode="eval")
    except SyntaxError as exc:
        raise ValueError("Expression could not be parsed") from exc
    if sum(1 for _ in ast.walk(tree)) > MAX_AST_NODES:
        raise ValueError("Expression is too complex")
    return normalized, _polynomial(tree.body)


def _text(value: Fraction) -> str:
    return str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"


def _square_root(value: Fraction) -> Fraction | None:
    numerator, denominator = isqrt(value.numerator), isqrt(value.denominator)
    if numerator * numerator == value.numerator and denominator * denominator == value.denominator:
        return Fraction(numerator, denominator)
    return None


def _safe_value(value):
    if type(value) in (int, bool):
        if abs(value) > MAX_ABSOLUTE_VALUE:
            raise ValueError("Calculation exceeds the supported range")
        return value
    if type(value) is Fraction:
        _bounded((value, Fraction(0), Fraction(0)))
        return value
    if type(value) is float:
        if not math.isfinite(value) or abs(value) > MAX_ABSOLUTE_VALUE:
            raise ValueError("Calculation exceeds the supported range")
        return value
    if type(value) in (tuple, list) and len(value) <= 100:
        return type(value)(_safe_value(item) for item in value)
    raise ValueError("Unsupported calculation value")


def _display(value):
    if type(value) is Fraction:
        return _text(value)
    if type(value) in (tuple, list):
        return [_display(item) for item in value]
    return value


class _MathCode:
    """Interpret a small Python-like numeric subset; never call exec or eval."""

    def __init__(self):
        self.variables = {}
        self.steps = 0
        self.last_value = None

    def _step(self):
        self.steps += 1
        if self.steps > MAX_CODE_STEPS:
            raise ValueError("Calculation step limit exceeded")

    def _call(self, function, arguments):
        if function == "range":
            if not 1 <= len(arguments) <= 3 or any(type(arg) is not int for arg in arguments):
                raise ValueError("range requires one to three integers")
            value = range(*arguments)
            if len(value) > MAX_LOOP_ITEMS:
                raise ValueError("Loop is too large")
            return value
        if function == "Fraction":
            if not 1 <= len(arguments) <= 2 or any(type(arg) not in (int, Fraction) for arg in arguments):
                raise ValueError("Fraction requires one or two numeric arguments")
            return _safe_value(Fraction(*arguments))
        if function in ("sum", "min", "max"):
            if len(arguments) != 1 or type(arguments[0]) not in (tuple, list, range):
                raise ValueError(f"{function} requires one bounded sequence")
            items = arguments[0]
            if len(items) > MAX_LOOP_ITEMS:
                raise ValueError("Sequence is too large")
            if function == "sum":
                return _safe_value(sum(items))
            return _safe_value(min(items) if function == "min" else max(items))
        if function == "len":
            if len(arguments) != 1 or type(arguments[0]) not in (tuple, list, range):
                raise ValueError("len requires one bounded sequence")
            return len(arguments[0])
        if function in ("abs", "round"):
            if len(arguments) not in (1, 2) or function == "abs" and len(arguments) != 1:
                raise ValueError(f"Invalid arguments for {function}")
            return _safe_value(abs(arguments[0]) if function == "abs" else round(*arguments))
        if function in SAFE_MATH_FUNCTIONS:
            if function == "factorial" and (len(arguments) != 1 or type(arguments[0]) is not int
                                            or not 0 <= arguments[0] <= 20):
                raise ValueError("factorial supports integers from 0 to 20")
            if function == "isqrt" and (len(arguments) != 1 or type(arguments[0]) is not int
                                         or not 0 <= arguments[0] <= MAX_ABSOLUTE_VALUE):
                raise ValueError("isqrt requires a bounded nonnegative integer")
            try:
                return _safe_value(SAFE_MATH_FUNCTIONS[function](*arguments))
            except (OverflowError, ZeroDivisionError, ValueError, TypeError) as exc:
                raise ValueError(f"Invalid input for {function}") from exc
        raise ValueError("Function is not available in math code")

    def expression(self, node):
        self._step()
        if isinstance(node, ast.Constant):
            return _safe_value(node.value)
        if isinstance(node, ast.Name):
            if node.id in self.variables:
                return self.variables[node.id]
            if node.id == "pi":
                return math.pi
            if node.id == "e":
                return math.e
            raise ValueError("Unknown calculation variable")
        if isinstance(node, (ast.Tuple, ast.List)):
            return _safe_value((tuple if isinstance(node, ast.Tuple) else list)(
                self.expression(item) for item in node.elts))
        if isinstance(node, ast.Subscript):
            sequence, index = self.expression(node.value), self.expression(node.slice)
            if type(sequence) not in (tuple, list, range) or type(index) is not int:
                raise ValueError("Only numeric sequence indexing is supported")
            return _safe_value(sequence[index])
        if isinstance(node, ast.UnaryOp):
            value = self.expression(node.operand)
            if isinstance(node.op, ast.USub):
                return _safe_value(-value)
            if isinstance(node.op, ast.UAdd):
                return _safe_value(+value)
            if isinstance(node.op, ast.Not):
                return not value
        if isinstance(node, ast.BinOp):
            left, right = self.expression(node.left), self.expression(node.right)
            if type(left) not in (int, float, Fraction) or type(right) not in (int, float, Fraction):
                raise ValueError("Arithmetic operands must be numeric")
            try:
                if isinstance(node.op, ast.Add):
                    value = left + right
                elif isinstance(node.op, ast.Sub):
                    value = left - right
                elif isinstance(node.op, ast.Mult):
                    value = left * right
                elif isinstance(node.op, ast.Div):
                    value = Fraction(left, right) if type(left) is int and type(right) is int else left / right
                elif isinstance(node.op, ast.FloorDiv):
                    value = left // right
                elif isinstance(node.op, ast.Mod):
                    value = left % right
                elif isinstance(node.op, ast.Pow):
                    if type(right) is not int or abs(right) > 20:
                        raise ValueError("Exponent exceeds the supported range")
                    value = left ** right
                else:
                    raise ValueError("Unsupported arithmetic operator")
            except (OverflowError, ZeroDivisionError) as exc:
                raise ValueError("Invalid arithmetic operation") from exc
            return _safe_value(value)
        if isinstance(node, ast.Compare):
            left = self.expression(node.left)
            for operator, comparator in zip(node.ops, node.comparators):
                right = self.expression(comparator)
                if isinstance(operator, ast.Lt):
                    passed = left < right
                elif isinstance(operator, ast.LtE):
                    passed = left <= right
                elif isinstance(operator, ast.Gt):
                    passed = left > right
                elif isinstance(operator, ast.GtE):
                    passed = left >= right
                elif isinstance(operator, ast.Eq):
                    passed = left == right
                elif isinstance(operator, ast.NotEq):
                    passed = left != right
                else:
                    raise ValueError("Unsupported comparison")
                if not passed:
                    return False
                left = right
            return True
        if isinstance(node, ast.Call) and not node.keywords:
            if isinstance(node.func, ast.Name):
                function = node.func.id
            elif (isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                  and node.func.value.id == "math" and node.func.attr in SAFE_MATH_FUNCTIONS):
                function = node.func.attr
            else:
                raise ValueError("Only approved math functions can be called")
            return self._call(function, [self.expression(arg) for arg in node.args])
        raise ValueError("Unsupported math code expression")

    def statement(self, node):
        self._step()
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name.startswith("_") or name in ("math", "range", "Fraction"):
                raise ValueError("Invalid calculation variable name")
            self.variables[name] = _safe_value(self.expression(node.value))
            return
        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
            if name not in self.variables:
                raise ValueError("Unknown calculation variable")
            self.statement(ast.Assign(targets=[ast.Name(id=name, ctx=ast.Store())],
                                      value=ast.BinOp(left=ast.Constant(value=self.variables[name]),
                                                      op=node.op, right=node.value)))
            return
        if isinstance(node, ast.Expr):
            self.last_value = self.expression(node.value)
            return
        if isinstance(node, ast.For) and isinstance(node.target, ast.Name) and not node.orelse:
            values = self.expression(node.iter)
            if type(values) not in (range, tuple, list) or len(values) > MAX_LOOP_ITEMS:
                raise ValueError("for requires a bounded numeric sequence")
            if node.target.id.startswith("_"):
                raise ValueError("Invalid loop variable")
            for value in values:
                self._step()
                self.variables[node.target.id] = _safe_value(value)
                for statement in node.body:
                    self.statement(statement)
            return
        if isinstance(node, ast.If):
            for statement in node.body if self.expression(node.test) else node.orelse:
                self.statement(statement)
            return
        raise ValueError("Unsupported math code statement")


def _run_math_code(code: str) -> dict:
    if not isinstance(code, str) or not code.strip() or len(code) > MAX_CODE_LENGTH:
        raise ValueError("Provide a short calculation program")
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as exc:
        raise ValueError("Calculation code could not be parsed") from exc
    if sum(1 for _ in ast.walk(tree)) > MAX_CODE_NODES:
        raise ValueError("Calculation code is too complex")
    runner = _MathCode()
    for statement in tree.body:
        runner.statement(statement)
    value = runner.variables.get("result", runner.last_value)
    if value is None:
        raise ValueError("Set result or end with a numeric expression")
    return {"task": "code", "result": _display(_safe_value(value)),
            "exact": type(value) in (int, bool, Fraction), "steps": runner.steps,
            "note": "Floating-point results are approximate; verify that the program models the user's question"}


def calculate_math(arguments: dict) -> dict:
    """Evaluate arithmetic, solve a quadratic, or interpret bounded math code."""
    if not isinstance(arguments, dict):
        raise ValueError("Calculation arguments must be an object")
    task = arguments.get("task")
    if task == "code":
        return _run_math_code(arguments.get("code"))
    expression, coefficients = _parse(arguments.get("expression"))
    c, b, a = coefficients
    result = {"task": task, "expression": expression,
              "coefficients": {"a": _text(a), "b": _text(b), "c": _text(c)}}
    if task == "evaluate":
        x_value = arguments.get("x_value")
        if (b or a) and x_value is None:
            raise ValueError("x_value is required when the expression contains x")
        x = Fraction(str(x_value)) if x_value is not None else Fraction(0)
        if abs(x.numerator) > MAX_ABSOLUTE_VALUE or x.denominator > MAX_ABSOLUTE_VALUE:
            raise ValueError("x_value exceeds the supported range")
        value = c + b * x + a * x * x
        _bounded((value, Fraction(0), Fraction(0)))
        result.update(x_value=_text(x) if x_value is not None else None, value=_text(value))
        return result
    if task != "quadratic":
        raise ValueError("task must be evaluate or quadratic")
    if not a:
        raise ValueError("Expression is not quadratic")
    discriminant = b * b - 4 * a * c
    vertex_x, vertex_y = -b / (2 * a), c - b * b / (4 * a)
    _bounded((discriminant, vertex_x, vertex_y))
    result.update(discriminant=_text(discriminant),
                  vertex={"x": _text(vertex_x), "y": _text(vertex_y)})
    if discriminant < 0:
        result["real_roots"] = []
        result["note"] = "No real roots; complex roots are outside this tool's scope"
        return result
    root = _square_root(discriminant)
    if root is not None:
        roots = sorted({(-b - root) / (2 * a), (-b + root) / (2 * a)})
        result["real_roots"] = [_text(value) for value in roots]
        if len(roots) == 2:
            terms = [-value for value in roots]
            result["factor_pair"] = {"numbers": [_text(value) for value in terms],
                                     "sum": _text(sum(terms)), "product": _text(terms[0] * terms[1])}
    else:
        low, high = sorted(((-float(b) - sqrt(float(discriminant))) / (2 * float(a)),
                            (-float(b) + sqrt(float(discriminant))) / (2 * float(a))))
        result["real_roots_approx"] = [round(low, 12), round(high, 12)]
        result["real_roots_exact"] = f"(-({_text(b)}) ± sqrt({_text(discriminant)})) / (2*({_text(a)}))"
    return result
