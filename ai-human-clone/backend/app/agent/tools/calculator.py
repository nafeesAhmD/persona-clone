"""calculator: safe arithmetic. NEVER eval/exec.

The expression is parsed with ast.parse(mode="eval") and walked by a tiny interpreter
that accepts only: int/float literals, + - * / // % **, unary + and -, parentheses,
the functions sqrt abs round min max sin cos tan log log10 exp floor ceil, and the
constants pi and e. Anything else (names, attributes, subscripts, lambdas, strings,
comprehensions, keyword arguments...) is rejected before evaluation.

Abuse limits: the expression is at most 200 characters (only digits, letters, spaces
and + - * / % ( ) . , are allowed), at most 60 operations/values, powers are checked
before they are computed (9**9**9 is refused, not computed), and every intermediate
value must stay finite and within 1e100.
"""

import ast
import math
import operator
from collections.abc import Callable
from typing import Any

from app.agent.exceptions import ToolInputError
from app.agent.schemas import RiskLevel, ToolContext, ToolResult
from app.agent.tool_registry import Tool, register
from app.agent.tools._common import check_object, string_arg

MAX_EXPRESSION = 200
MAX_NODES = 60
MAX_MAGNITUDE = 1e100
MAX_INT = 10**100
MAX_EXPONENT = 10_000
ALLOWED_CHARS = frozenset("0123456789.+-*/%(), \t" + "abcdefghijklmnopqrstuvwxyz" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ")

_BINARY: dict[type, Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY: dict[type, Callable[[Any], Any]] = {ast.UAdd: operator.pos, ast.USub: operator.neg}
# name -> (function, min args, max args)
_FUNCTIONS: dict[str, tuple[Callable[..., Any], int, int]] = {
    "sqrt": (math.sqrt, 1, 1),
    "abs": (abs, 1, 1),
    "round": (round, 1, 2),
    "min": (min, 2, 20),
    "max": (max, 2, 20),
    "sin": (math.sin, 1, 1),
    "cos": (math.cos, 1, 1),
    "tan": (math.tan, 1, 1),
    "log": (math.log, 1, 2),
    "log10": (math.log10, 1, 1),
    "exp": (math.exp, 1, 1),
    "floor": (math.floor, 1, 1),
    "ceil": (math.ceil, 1, 1),
}
_CONSTANTS = {"pi": math.pi, "e": math.e}


class CalculationError(Exception):
    """A valid expression whose value can't be computed (division by zero, domain, too large)."""


def parse_expression(expression: str) -> ast.Expression:
    """Parse and structurally check an expression; raises ToolInputError."""
    if len(expression) > MAX_EXPRESSION:
        raise ToolInputError(f"The expression must be at most {MAX_EXPRESSION} characters.")
    if "^" in expression:
        raise ToolInputError("Use ** for powers (for example 2**8).")
    if any(char not in ALLOWED_CHARS for char in expression):
        raise ToolInputError("The expression may only contain numbers, + - * / % ** ( ) and math functions.")
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        raise ToolInputError("The expression is not valid arithmetic.") from None
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.operator, ast.unaryop, ast.expr_context)):
            continue
        count += 1
        if count > MAX_NODES:
            raise ToolInputError("The expression is too long.")
        _check_node(node)
    return tree


def _check_node(node: ast.AST) -> None:
    if isinstance(node, ast.Expression):
        return
    if isinstance(node, ast.Constant):
        value = node.value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ToolInputError("Only numbers are allowed.")
        _check_value(value, input_error=True)
        return
    if isinstance(node, ast.BinOp):
        if type(node.op) not in _BINARY:
            raise ToolInputError("That operator is not allowed.")
        return
    if isinstance(node, ast.UnaryOp):
        if type(node.op) not in _UNARY:
            raise ToolInputError("That operator is not allowed.")
        return
    if isinstance(node, ast.Name):
        if node.id not in _CONSTANTS and node.id not in _FUNCTIONS:
            raise ToolInputError("Unknown name in the expression.")
        return
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCTIONS:
            raise ToolInputError("Only the listed math functions may be called.")
        if node.keywords:
            raise ToolInputError("Keyword arguments are not allowed.")
        _, low, high = _FUNCTIONS[node.func.id]
        if not low <= len(node.args) <= high:
            raise ToolInputError(f"Wrong number of arguments for {node.func.id}().")
        if any(isinstance(arg, ast.Starred) for arg in node.args):
            raise ToolInputError("That syntax is not allowed.")
        return
    raise ToolInputError("That syntax is not allowed in a calculation.")


def _check_value(value: Any, *, input_error: bool = False) -> Any:
    error = ToolInputError if input_error else CalculationError
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise error("The result is not a real number.")
    if isinstance(value, float) and not math.isfinite(value):
        raise error("The result is too large or undefined.")
    if (isinstance(value, int) and abs(value) > MAX_INT) or (isinstance(value, float) and abs(value) > MAX_MAGNITUDE):
        raise error("The number is too large (limit 1e100).")
    return value


def _check_power(base: Any, exponent: Any) -> None:
    if abs(exponent) > MAX_EXPONENT:
        raise CalculationError("The exponent is too large.")
    if base == 0:
        if exponent < 0:
            raise CalculationError("Division by zero.")
        return
    magnitude = abs(exponent) * abs(math.log10(abs(base)))
    if magnitude > 100 and ((abs(base) > 1) == (exponent > 0)):
        raise CalculationError("The result is too large (limit 1e100).")
    if base < 0 and isinstance(exponent, float) and not exponent.is_integer():
        raise CalculationError("The result is not a real number.")


def _evaluate(node: ast.AST) -> Any:
    if isinstance(node, ast.Expression):
        return _evaluate(node.body)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in _CONSTANTS:
            return _CONSTANTS[node.id]
        raise CalculationError("A function name must be called, e.g. sqrt(2).")
    if isinstance(node, ast.UnaryOp):
        return _check_value(_UNARY[type(node.op)](_evaluate(node.operand)))
    if isinstance(node, ast.BinOp):
        left, right = _evaluate(node.left), _evaluate(node.right)
        if isinstance(node.op, ast.Pow):
            _check_power(left, right)
        return _check_value(_BINARY[type(node.op)](left, right))
    if isinstance(node, ast.Call):
        function, _, _ = _FUNCTIONS[node.func.id]  # type: ignore[union-attr]
        args = [_evaluate(arg) for arg in node.args]
        if node.func.id == "round" and len(args) == 2:  # type: ignore[union-attr]
            if not isinstance(args[1], int) or abs(args[1]) > 15:
                raise CalculationError("round() digits must be a whole number between -15 and 15.")
        return _check_value(function(*args))
    raise CalculationError("That syntax is not allowed in a calculation.")  # unreachable after parse checks


def calculate(expression: str) -> int | float:
    """Evaluate a checked expression. Raises ToolInputError or CalculationError."""
    tree = parse_expression(expression)
    try:
        result = _evaluate(tree)
    except CalculationError:
        raise
    except ZeroDivisionError:
        raise CalculationError("Division by zero.") from None
    except (ValueError, OverflowError, TypeError, ArithmeticError):
        raise CalculationError("The calculation is undefined for these values.") from None
    if isinstance(result, float):
        result = float(f"{result:.12g}")  # hide float noise like 0.30000000000000004
    return result


class CalculatorTool(Tool):
    name = "calculator"
    title = "Calculator"
    description = (
        "Evaluate an arithmetic expression exactly, e.g. '(1250 * 12) / 7' or 'sqrt(2) * pi'. "
        "Supports numbers, + - * / // % **, parentheses, sqrt abs round min max sin cos tan log "
        "log10 exp floor ceil, and the constants pi and e. Max 200 characters. Use it instead of "
        "doing arithmetic in your head."
    )
    permission_scope = "calculator:use"
    risk = RiskLevel.LOW
    timeout_seconds = 2.0
    enabled_by_default = True
    confirmation_by_default = False
    public_safe = True
    input_schema = {
        "type": "object",
        "properties": {"expression": {"type": "string", "minLength": 1, "maxLength": MAX_EXPRESSION}},
        "required": ["expression"],
        "additionalProperties": False,
    }
    output_schema = {
        "type": "object",
        "properties": {"expression": {"type": "string"}, "result": {"type": "number"}},
    }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        check_object(arguments, {"expression"}, {"expression"})
        expression = string_arg(arguments, "expression", max_length=MAX_EXPRESSION)
        parse_expression(expression)
        return {"expression": expression}

    def run(self, ctx: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        expression = arguments["expression"]
        try:
            result = calculate(expression)
        except (ToolInputError, CalculationError) as exc:
            return ToolResult(ok=False, error=str(exc), summary="The calculation could not be done")
        return ToolResult(
            ok=True,
            data={"expression": expression, "result": result},
            summary=f"Calculated {expression} = {result}",
        )


register(CalculatorTool())
