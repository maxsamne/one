"""Calc tools — safe math evaluation and date arithmetic."""

import ast
import operator
from datetime import date, datetime

from core.ai_client.models import Tool

_OPS: dict[type, object] = {
    ast.Add:  operator.add,
    ast.Sub:  operator.sub,
    ast.Mult: operator.mul,
    ast.Div:  operator.truediv,
    ast.Mod:  operator.mod,
    ast.Pow:  operator.pow,
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _eval(node: ast.expr) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp):
        op = _OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
        return op(_eval(node.left), _eval(node.right))  # type: ignore[operator]
    if isinstance(node, ast.UnaryOp):
        op = _OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
        return op(_eval(node.operand))  # type: ignore[operator]
    raise ValueError(f"Unsupported node: {type(node).__name__}")


async def calculate(expression: str) -> str:
    try:
        expr = expression.strip().replace("^", "**")
        tree = ast.parse(expr, mode="eval")
        result = _eval(tree.body)
        if result == int(result) and abs(result) < 1e15:
            return str(int(result))
        return f"{result:.6g}"
    except Exception as e:
        return f"FATAL: {e}"


async def months_between(start_date: str, end_date: str) -> str:
    try:
        def _parse(d: str) -> date:
            return date.today() if d.strip().lower() == "today" else datetime.strptime(d.strip(), "%Y-%m-%d").date()
        s, e = _parse(start_date), _parse(end_date)
        return str((e.year - s.year) * 12 + (e.month - s.month))
    except Exception as ex:
        return f"FATAL: {ex}"


CALC_TOOLS = [
    Tool(
        name="calculate",
        description=(
            "Evaluate a math expression — growth rates, multiples, market sizing, capital requirements, etc. "
            "Supports +, -, *, /, %, ^ (power), parentheses."
        ),
        parameters={
            "type": "object",
            "properties": {"expression": {"type": "string", "description": "Math expression, e.g. '(150 - 100) / 100 * 100'"}},
            "required": ["expression"],
        },
        fn=calculate,
        is_read_only=True,
        is_concurrency_safe=True,
    ),
    Tool(
        name="months_between",
        description=(
            "Calculate the number of months between two dates. "
            "Use for company age, time since funding, founder tenure, etc."
        ),
        parameters={
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "description": "ISO date YYYY-MM-DD or 'today'"},
                "end_date":   {"type": "string", "description": "ISO date YYYY-MM-DD or 'today'"},
            },
            "required": ["start_date", "end_date"],
        },
        fn=months_between,
        is_read_only=True,
        is_concurrency_safe=True,
    ),
]
