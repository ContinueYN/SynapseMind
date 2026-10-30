"""Physics PARTIAL verifier: units first, then numeric replay (M2.5 S6 follow-up).

The PARTIAL promise in chapter 13 §13.3 is narrower than math's STRONG tier:

* a scalar equation is dimensionally consistent, and
* substituting the student's values into both sides agrees within tolerance.

Both checks are falsifiers. ``pass`` means "no inconsistency was found in the
checks that actually ran", not "the physics is proved". Missing symbols or
units produce ``unknown`` with a concrete reason; when values are missing only
the dimension check runs, and the detail says that numeric replay was skipped.
No natural-language guessing and no regex extraction of units from prose.

Safety: student input is untrusted. Expressions are parsed with :mod:`ast` and
interpreted by a small whitelist evaluator -- never ``eval``/``exec``. The
allowed grammar is numbers, declared symbols, ``+ - * / **``, parentheses,
``pi`` and ``sin/cos/tan/asin/acos/atan/sqrt/exp/log/ln/abs``. Attribute access,
subscripts, comprehensions, lambdas, strings and unknown functions are rejected.
"""

from __future__ import annotations

import ast
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from typing import Final, cast

from synapse.application.subject import StudentStep, Verdict

# Seven SI base dimensions, in this order: kg, m, s, A, K, mol, cd.
Dimension = tuple[
    Fraction,
    Fraction,
    Fraction,
    Fraction,
    Fraction,
    Fraction,
    Fraction,
]

_ZERO: Dimension = (
    Fraction(0),
    Fraction(0),
    Fraction(0),
    Fraction(0),
    Fraction(0),
    Fraction(0),
    Fraction(0),
)

_BASE_SYMBOLS: Final = ("kg", "m", "s", "A", "K", "mol", "cd")
_FUNCTIONS: Final = frozenset(
    {"sin", "cos", "tan", "asin", "acos", "atan", "sqrt", "exp", "log", "ln", "abs"}
)
_DIMENSIONLESS_FUNCTIONS: Final = frozenset(
    {"sin", "cos", "tan", "asin", "acos", "atan", "exp", "log", "ln"}
)
_ALLOWED_CHARACTERS = re.compile(r"^[0-9A-Za-z_+\-*/^().,\s]+$")
_MAX_TEXT = 1000
_MAX_NODES = 256
_MAX_UNITS = 64
_MAX_EXPONENT = 100

_UNIT_SUFFIXES = {
    "²": "**2",
    "³": "**3",
    "×": "*",
    "·": "*",
    "÷": "/",
    "−": "-",
    "π": "pi",
    "Ω": "ohm",
    "μ": "u",
    "µ": "u",
    "√": "sqrt",
}


class _UnitError(ValueError):
    """Input cannot be read or references an unknown unit/symbol."""


class _DimensionMismatch(ValueError):
    """The input is readable, but its dimensions disagree (a concrete fail)."""


@dataclass(frozen=True, slots=True)
class Unit:
    """A unit expression reduced to an SI scale and a dimension vector."""

    scale: float
    dimension: Dimension


@dataclass(frozen=True, slots=True)
class _Tolerance:
    relative: float = 1e-6
    absolute: float = 1e-9


def _dimension(
    *,
    kg: int = 0,
    m: int = 0,
    s: int = 0,
    ampere: int = 0,
    kelvin: int = 0,
    mol: int = 0,
    candela: int = 0,
) -> Dimension:
    return (
        Fraction(kg),
        Fraction(m),
        Fraction(s),
        Fraction(ampere),
        Fraction(kelvin),
        Fraction(mol),
        Fraction(candela),
    )


_KG = _dimension(kg=1)
_M = _dimension(m=1)
_S = _dimension(s=1)
_A = _dimension(ampere=1)
_K = _dimension(kelvin=1)
_MOL = _dimension(mol=1)
_CD = _dimension(candela=1)

_N = _dimension(kg=1, m=1, s=-2)
_J = _dimension(kg=1, m=2, s=-2)
_W = _dimension(kg=1, m=2, s=-3)
_PA = _dimension(kg=1, m=-1, s=-2)
_C = _dimension(ampere=1, s=1)
_V = _dimension(kg=1, m=2, s=-3, ampere=-1)
_OHM = _dimension(kg=1, m=2, s=-3, ampere=-2)
_HZ = _dimension(s=-1)
_F = _dimension(kg=-1, m=-2, s=4, ampere=2)
_T = _dimension(kg=1, s=-2, ampere=-1)
_WB = _dimension(kg=1, m=2, s=-2, ampere=-1)
_SIEMENS = _dimension(kg=-1, m=-2, s=3, ampere=2)
_HENRY = _dimension(kg=1, m=2, s=-2, ampere=-2)


# Explicit table: no generic prefix parser, because ``m`` (metre), ``M``
# (mega) and ``min`` (minute) make prefix guessing ambiguous. Add entries as a
# subject needs them rather than silently misreading an unknown symbol.
UNITS: dict[str, Unit] = {
    # SI base
    "kg": Unit(1.0, _KG),
    "g": Unit(1e-3, _KG),
    "mg": Unit(1e-6, _KG),
    "m": Unit(1.0, _M),
    "cm": Unit(1e-2, _M),
    "mm": Unit(1e-3, _M),
    "km": Unit(1e3, _M),
    "s": Unit(1.0, _S),
    "ms": Unit(1e-3, _S),
    "us": Unit(1e-6, _S),
    "min": Unit(60.0, _S),
    "h": Unit(3600.0, _S),
    "A": Unit(1.0, _A),
    "mA": Unit(1e-3, _A),
    "uA": Unit(1e-6, _A),
    "K": Unit(1.0, _K),
    "mol": Unit(1.0, _MOL),
    "cd": Unit(1.0, _CD),
    # Mechanics / energy / power / pressure
    "N": Unit(1.0, _N),
    "kN": Unit(1e3, _N),
    "J": Unit(1.0, _J),
    "kJ": Unit(1e3, _J),
    "MJ": Unit(1e6, _J),
    "W": Unit(1.0, _W),
    "kW": Unit(1e3, _W),
    "Pa": Unit(1.0, _PA),
    "kPa": Unit(1e3, _PA),
    "MPa": Unit(1e6, _PA),
    # Electromagnetism
    "C": Unit(1.0, _C),
    "V": Unit(1.0, _V),
    "mV": Unit(1e-3, _V),
    "kV": Unit(1e3, _V),
    "ohm": Unit(1.0, _OHM),
    "kohm": Unit(1e3, _OHM),
    "Mohm": Unit(1e6, _OHM),
    "Hz": Unit(1.0, _HZ),
    "kHz": Unit(1e3, _HZ),
    "F": Unit(1.0, _F),
    "uF": Unit(1e-6, _F),
    "T": Unit(1.0, _T),
    "Wb": Unit(1.0, _WB),
    "S": Unit(1.0, _SIEMENS),
    "H": Unit(1.0, _HENRY),
    # Volume / angle
    "L": Unit(1e-3, _dimension(m=3)),
    "rad": Unit(1.0, _ZERO),
    "deg": Unit(math.pi / 180.0, _ZERO),
}


def _normalize(text: str) -> str:
    for source, target in _UNIT_SUFFIXES.items():
        text = text.replace(source, target)
    return text.replace("^", "**").strip()


def _parse(text: str, what: str) -> ast.expr:
    if not isinstance(text, str):
        raise _UnitError(f"{what} 必须是字符串")
    if len(text) > _MAX_TEXT:
        raise _UnitError(f"{what} 过长（上限 {_MAX_TEXT} 字符）")
    normalized = _normalize(text)
    if not normalized:
        raise _UnitError(f"{what} 为空")
    if not _ALLOWED_CHARACTERS.match(normalized):
        raise _UnitError(f"{what} 含不允许的字符")
    try:
        tree = ast.parse(normalized, mode="eval")
    except (SyntaxError, ValueError, RecursionError) as exc:
        raise _UnitError(f"{what} 语法不合法：{exc}") from exc
    if not isinstance(tree, ast.Expression):
        raise _UnitError(f"{what} 不是单个表达式")
    if sum(1 for _ in ast.walk(tree)) > _MAX_NODES:
        raise _UnitError(f"{what} 过于复杂（上限 {_MAX_NODES} 个语法节点）")
    _validate(tree.body, what)
    return tree.body


def _validate(node: ast.AST, what: str) -> None:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise _UnitError(f"{what} 只允许数字常量")
        return
    if isinstance(node, ast.Name):
        return
    if isinstance(node, ast.BinOp):
        if not isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)):
            raise _UnitError(f"{what} 只允许 + - * / **")
        _validate(node.left, what)
        _validate(node.right, what)
        return
    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, (ast.UAdd, ast.USub)):
            raise _UnitError(f"{what} 只允许一元 + -")
        _validate(node.operand, what)
        return
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCTIONS:
            raise _UnitError(f"{what} 含未知函数")
        if node.keywords:
            raise _UnitError(f"{what} 的函数不接受关键字参数")
        if len(node.args) != 1:
            raise _UnitError(f"{what} 的函数只接收一个参数")
        _validate(node.args[0], what)
        return
    raise _UnitError(f"{what} 含不支持的语法：{type(node).__name__}")


def _constant_value(node: ast.AST) -> float:
    """Evaluate a numeric-only subtree for exponents and unit scales."""

    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise _UnitError("只允许数字常量")
        try:
            value = float(node.value)
        except (OverflowError, ValueError) as exc:
            raise _UnitError(f"数值无法读取：{exc}") from exc
        if not math.isfinite(value):
            raise _UnitError("数值必须是有限数")
        return value
    if isinstance(node, ast.UnaryOp):
        operand = _constant_value(node.operand)
        if isinstance(node.op, ast.UAdd):
            return operand
        if isinstance(node.op, ast.USub):
            return -operand
        raise _UnitError("只允许一元 + -")
    if isinstance(node, ast.BinOp):
        left = _constant_value(node.left)
        right = _constant_value(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            if right == 0:
                raise _UnitError("除数为零")
            return left / right
        if isinstance(node.op, ast.Pow):
            if abs(right) > _MAX_EXPONENT:
                raise _UnitError(f"幂指数绝对值不能超过 {_MAX_EXPONENT}")
            try:
                result = left**right
            except (OverflowError, ValueError, ZeroDivisionError) as exc:
                raise _UnitError(f"指数无法计算：{exc}") from exc
            if isinstance(result, complex) or not math.isfinite(result):
                raise _UnitError("指数结果不是有限实数")
            return float(result)
        raise _UnitError("只允许 + - * / **")
    raise _UnitError("这里只允许数值常量")


def _constant_fraction(node: ast.AST) -> Fraction:
    value = _constant_value(node)
    if abs(value) > _MAX_EXPONENT:
        raise _UnitError(f"幂指数绝对值不能超过 {_MAX_EXPONENT}")
    return Fraction(value).limit_denominator(1_000_000)


def _finite_constant(value: float) -> float:
    if not math.isfinite(value):
        raise _UnitError("数值常量不是有限数")
    return value


def _scale_dimension(dimension: Dimension, exponent: Fraction) -> Dimension:
    return cast(Dimension, tuple(component * exponent for component in dimension))


def _add_dimensions(left: Dimension, right: Dimension, sign: int = 1) -> Dimension:
    return cast(Dimension, tuple(a + sign * b for a, b in zip(left, right, strict=True)))


def _unit_node(node: ast.AST) -> Unit:
    if isinstance(node, ast.Constant):
        scale = _constant_value(node)
        if scale <= 0:
            raise _UnitError("单位换算系数必须为正数")
        return Unit(scale, _ZERO)
    if isinstance(node, ast.Name):
        unit = UNITS.get(node.id)
        if unit is None:
            raise _UnitError(f"未知单位 {node.id!r}")
        return unit
    if isinstance(node, ast.BinOp):
        if isinstance(node.op, ast.Mult):
            left = _unit_node(node.left)
            right = _unit_node(node.right)
            return Unit(left.scale * right.scale, _add_dimensions(left.dimension, right.dimension))
        if isinstance(node.op, ast.Div):
            left = _unit_node(node.left)
            right = _unit_node(node.right)
            if right.scale == 0:
                raise _UnitError("单位换算的除数为零")
            return Unit(
                left.scale / right.scale,
                _add_dimensions(left.dimension, right.dimension, sign=-1),
            )
        if isinstance(node.op, ast.Pow):
            base = _unit_node(node.left)
            exponent = _constant_fraction(node.right)
            try:
                scale = base.scale ** float(exponent)
            except (OverflowError, ValueError) as exc:
                raise _UnitError(f"单位幂无法计算：{exc}") from exc
            if not math.isfinite(scale):
                raise _UnitError("单位幂不是有限数")
            return Unit(scale, _scale_dimension(base.dimension, exponent))
        raise _UnitError("单位只允许 * / **")
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        # ``-m`` is not a unit; reject rather than inventing a negative scale.
        raise _UnitError("单位不能带一元正负号")
    raise _UnitError("单位表达式只允许单位名、数字、* / **")


def parse_unit(text: str) -> Unit:
    """Reduce a unit expression such as ``"kg*m/s^2"`` to SI scale/dimension.

    Raises ``ValueError`` for an unknown unit or malformed expression. An empty
    string is the dimensionless unit. This function never evaluates Python.
    """

    if not isinstance(text, str):
        raise _UnitError("单位必须是字符串")
    if not text.strip():
        return Unit(1.0, _ZERO)
    return _unit_node(_parse(text, "单位"))


def _dimension_node(node: ast.AST, units: Mapping[str, Unit]) -> Dimension:
    if isinstance(node, ast.Constant):
        _constant_value(node)
        return _ZERO
    if isinstance(node, ast.Name):
        if node.id == "pi":
            return _ZERO
        unit = units.get(node.id)
        if unit is None:
            raise _UnitError(f"符号 {node.id!r} 没有声明单位（无量纲请写空字符串）")
        return unit.dimension
    if isinstance(node, ast.BinOp):
        left = _dimension_node(node.left, units)
        right = _dimension_node(node.right, units)
        if isinstance(node.op, ast.Add):
            if left != right:
                raise _DimensionMismatch(
                    f"加法两侧量纲不一致：{render_dimension(left)} 与 {render_dimension(right)}"
                )
            return left
        if isinstance(node.op, ast.Sub):
            if left != right:
                raise _DimensionMismatch(
                    f"减法两侧量纲不一致：{render_dimension(left)} 与 {render_dimension(right)}"
                )
            return left
        if isinstance(node.op, ast.Mult):
            return _add_dimensions(left, right)
        if isinstance(node.op, ast.Div):
            return _add_dimensions(left, right, sign=-1)
        if isinstance(node.op, ast.Pow):
            exponent = _constant_fraction(node.right)
            return _scale_dimension(left, exponent)
        raise _UnitError("表达式只允许 + - * / **")
    if isinstance(node, ast.UnaryOp):
        return _dimension_node(node.operand, units)
    if isinstance(node, ast.Call):
        argument = _dimension_node(node.args[0], units)
        name = node.func.id  # type: ignore[attr-defined]
        if name in _DIMENSIONLESS_FUNCTIONS:
            if argument != _ZERO:
                raise _DimensionMismatch(
                    f"{name}() 的参数量纲必须是无量纲，实际是 {render_dimension(argument)}"
                )
            return _ZERO
        if name == "sqrt":
            return _scale_dimension(argument, Fraction(1, 2))
        if name == "abs":
            return argument
        raise _UnitError(f"未知函数 {name!r}")
    raise _UnitError("表达式含不支持的语法")


def dimension_of(expression: str, units: Mapping[str, str]) -> Dimension:
    """Return the dimension of ``expression`` given ``symbol -> unit``.

    Raises ``ValueError`` when the expression cannot be read, a symbol has no
    unit, or a unit name is unknown. A readable dimension mismatch is a
    ``ValueError`` too; callers that need to distinguish it should use
    :func:`verify_step`.
    """

    parsed_units = _unit_map(units)
    return _dimension_node(_parse(expression, "表达式"), parsed_units)


def _unit_map(units: Mapping[str, object]) -> dict[str, Unit]:
    if not isinstance(units, Mapping):
        raise _UnitError("units 必须是对象")
    if len(units) > _MAX_UNITS:
        raise _UnitError(f"units 过多（上限 {_MAX_UNITS} 个符号）")
    parsed: dict[str, Unit] = {}
    for name, raw in units.items():
        if not isinstance(name, str) or not name:
            raise _UnitError("units 的键必须是非空字符串")
        if not isinstance(raw, str):
            raise _UnitError(f"{name} 的单位必须是字符串")
        parsed[name] = parse_unit(raw)
    return parsed


def _free_symbols(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Name):
        return set() if node.id == "pi" else {node.id}
    if isinstance(node, ast.Call):
        return _free_symbols(node.args[0])
    if isinstance(node, ast.BinOp):
        return _free_symbols(node.left) | _free_symbols(node.right)
    if isinstance(node, ast.UnaryOp):
        return _free_symbols(node.operand)
    return set()


def _eval_node(node: ast.AST, values: Mapping[str, float]) -> float:
    if isinstance(node, ast.Constant):
        return _constant_value(node)
    if isinstance(node, ast.Name):
        if node.id == "pi":
            return math.pi
        if node.id not in values:
            raise _UnitError(f"符号 {node.id!r} 没有数值")
        return values[node.id]
    if isinstance(node, ast.BinOp):
        left = _eval_node(node.left, values)
        right = _eval_node(node.right, values)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            if right == 0:
                raise _UnitError("除数为零")
            return left / right
        if isinstance(node.op, ast.Pow):
            if abs(right) > _MAX_EXPONENT:
                raise _UnitError(f"幂指数绝对值不能超过 {_MAX_EXPONENT}")
            try:
                result = left**right
            except (OverflowError, ValueError, ZeroDivisionError) as exc:
                raise _UnitError(f"幂无法计算：{exc}") from exc
            if isinstance(result, complex) or not math.isfinite(result):
                raise _UnitError("幂结果不是有限实数")
            return float(result)
        raise _UnitError("表达式只允许 + - * / **")
    if isinstance(node, ast.UnaryOp):
        operand = _eval_node(node.operand, values)
        return operand if isinstance(node.op, ast.UAdd) else -operand
    if isinstance(node, ast.Call):
        argument = _eval_node(node.args[0], values)
        name = node.func.id  # type: ignore[attr-defined]
        try:
            if name == "sin":
                return math.sin(argument)
            if name == "cos":
                return math.cos(argument)
            if name == "tan":
                return math.tan(argument)
            if name == "asin":
                return math.asin(argument)
            if name == "acos":
                return math.acos(argument)
            if name == "atan":
                return math.atan(argument)
            if name == "sqrt":
                return math.sqrt(argument)
            if name == "exp":
                return math.exp(argument)
            if name in {"log", "ln"}:
                return math.log(argument)
            if name == "abs":
                return abs(argument)
        except (ValueError, OverflowError, ZeroDivisionError) as exc:
            raise _UnitError(f"{name}() 在给定数值下无定义：{exc}") from exc
        raise _UnitError(f"未知函数 {name!r}")
    raise _UnitError("表达式含不支持的语法")


def evaluate(expression: str, values: Mapping[str, float]) -> float:
    """Evaluate a validated expression with SI values; never calls Python eval."""

    node = _parse(expression, "表达式")
    missing = _free_symbols(node) - set(values)
    if missing:
        raise _UnitError(f"缺少数值：{', '.join(sorted(missing))}")
    result = _eval_node(node, values)
    if not math.isfinite(result):
        raise _UnitError("表达式结果不是有限数")
    return result


def render_dimension(dimension: Dimension) -> str:
    """Render a dimension vector in base SI units, e.g. ``kg·m·s^-2``."""

    if all(component == 0 for component in dimension):
        return "无量纲"
    numerator: list[str] = []
    denominator: list[str] = []
    for symbol, exponent in zip(_BASE_SYMBOLS, dimension, strict=True):
        if exponent == 0:
            continue
        target = numerator if exponent > 0 else denominator
        power = abs(exponent)
        if power == 1:
            target.append(symbol)
        elif power.denominator == 1:
            target.append(f"{symbol}^{power.numerator}")
        else:
            target.append(f"{symbol}^({power.numerator}/{power.denominator})")
    if not numerator:
        numerator = ["1"]
    if not denominator:
        return "·".join(numerator)
    denominator_text = "·".join(denominator)
    if len(denominator) > 1:
        denominator_text = f"({denominator_text})"
    return f"{'·'.join(numerator)}/{denominator_text}"


def _split_equation(text: str) -> tuple[str, str]:
    if text.count("=") != 1:
        raise _UnitError("equation 必须恰好包含一个 '='（不支持 ==、<=、>=）")
    left, right = text.split("=")
    if not left.strip() or not right.strip():
        raise _UnitError("equation 的等号两侧都必须有表达式")
    return left, right


def _number(value: object, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _UnitError(f"{what} 必须是数字")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise _UnitError(f"{what} 无法读取：{exc}") from exc
    if not math.isfinite(result):
        raise _UnitError(f"{what} 必须是有限数")
    return result


def _as_mapping(value: object, what: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise _UnitError(f"{what} 必须是对象")
    return value


def _parse_tolerance(raw: object) -> _Tolerance:
    if raw is None:
        return _Tolerance()
    if isinstance(raw, bool):
        raise _UnitError("tolerance 必须是数字或对象")
    if isinstance(raw, (int, float)):
        value = _number(raw, "tolerance")
        if value < 0:
            raise _UnitError("tolerance 不能为负数")
        return _Tolerance(relative=value, absolute=value)
    mapping = _as_mapping(raw, "tolerance")
    relative = _number(mapping.get("relative", 1e-6), "tolerance.relative")
    absolute = _number(mapping.get("absolute", 1e-9), "tolerance.absolute")
    if relative < 0 or absolute < 0:
        raise _UnitError("tolerance 不能为负数")
    return _Tolerance(relative=relative, absolute=absolute)


def _si_values(
    symbols: set[str],
    units: Mapping[str, Unit],
    raw_values: Mapping[str, object],
) -> dict[str, float] | None:
    values: dict[str, float] = {}
    for symbol in symbols:
        if symbol not in raw_values:
            return None
        unit = units.get(symbol)
        if unit is None:
            raise _UnitError(f"符号 {symbol!r} 没有声明单位")
        values[symbol] = _number(raw_values[symbol], f"values.{symbol}") * unit.scale
    return values


def _numbers_agree(left: float, right: float, tolerance: _Tolerance) -> bool:
    return math.isclose(
        left,
        right,
        rel_tol=tolerance.relative,
        abs_tol=tolerance.absolute,
    )


def _fmt(value: float) -> str:
    return f"{value:.6g}"


def _tolerance_text(tolerance: _Tolerance) -> str:
    return f"绝对 {tolerance.absolute:g} / 相对 {tolerance.relative:g}"


def _parse_expected(raw: object) -> tuple[float, Unit, str]:
    expected = _as_mapping(raw, "expected")
    value = _number(expected.get("value"), "expected.value")
    unit_text = expected.get("unit")
    if not isinstance(unit_text, str):
        raise _UnitError("expected.unit 必须是单位字符串")
    return value, parse_unit(unit_text), unit_text


def _check_expected(
    *,
    expected: tuple[float, Unit, str] | None,
    reference_dimension: Dimension,
    reference_value: float | None,
    reference_label: str,
    tolerance: _Tolerance,
) -> Verdict | None:
    """Return a verdict only when the expected result adds a failure."""

    if expected is None:
        return None
    value, unit, unit_text = expected
    if unit.dimension != reference_dimension:
        return Verdict(
            status="fail",
            detail=(
                f"结果单位不一致：声明 {unit_text!r} 的量纲是 {render_dimension(unit.dimension)}，"
                f"但{reference_label}的量纲是 {render_dimension(reference_dimension)}"
            ),
        )
    if reference_value is None:
        return Verdict(
            status="unknown",
            detail=(
                f"结果单位 {unit_text!r} 与{reference_label}一致，但缺少部分或全部符号的数值，"
                "无法回代检查声明结果"
            ),
        )
    expected_si = value * unit.scale
    if not math.isfinite(expected_si):
        raise _UnitError("expected 换算成 SI 后不是有限数")
    if not _numbers_agree(expected_si, reference_value, tolerance):
        return Verdict(
            status="fail",
            detail=(
                f"结果值不一致：声明 {_fmt(expected_si)}（{unit_text}）与{reference_label} "
                f"{_fmt(reference_value)}（SI）相差 "
                f"{_fmt(abs(expected_si - reference_value))}，超过容差 "
                f"({_tolerance_text(tolerance)})"
            ),
        )
    return None


def _verify_step(step: StudentStep) -> Verdict:
    data = step.data
    if data is None:
        return Verdict(
            status="unknown",
            detail=(
                "物理按 PARTIAL 档验证：需要 step.data 提供 equation/expression、units；"
                "只有纯文本时不做量纲猜测，也不判对错"
            ),
        )
    if not isinstance(data, Mapping):
        return Verdict(status="unknown", detail="step.data 必须是对象（键由学科约定）")

    equation_raw = data.get("equation")
    expression_raw = data.get("expression")
    if equation_raw is not None and expression_raw is not None:
        return Verdict(
            status="unknown",
            detail="step.data 不能同时给 equation 和 expression；请只保留学生实际写的那一种",
        )
    if equation_raw is None and expression_raw is None:
        return Verdict(
            status="unknown",
            detail=(
                "step.data 没有 equation 或 expression；PARTIAL 验证器不会从自然语言里猜单位或公式"
            ),
        )

    units = _unit_map(_as_mapping(data.get("units", {}), "units"))
    values = _as_mapping(data.get("values", {}), "values")
    tolerance = _parse_tolerance(data.get("tolerance"))
    expected_raw = data.get("expected")
    expected = _parse_expected(expected_raw) if expected_raw is not None else None
    declared_unit_raw = data.get("unit")

    if equation_raw is not None:
        if not isinstance(equation_raw, str):
            raise _UnitError("equation 必须是字符串")
        left_text, right_text = _split_equation(equation_raw)
        left = _parse(left_text, "equation 左侧")
        right = _parse(right_text, "equation 右侧")
        left_dimension = _dimension_node(left, units)
        right_dimension = _dimension_node(right, units)

        declared_note = ""
        if declared_unit_raw is not None:
            if not isinstance(declared_unit_raw, str):
                raise _UnitError("unit 必须是单位字符串")
            declared = parse_unit(declared_unit_raw)
            if declared.dimension != right_dimension:
                return Verdict(
                    status="fail",
                    detail=(
                        f"声明结果单位 {declared_unit_raw!r} 的量纲是 "
                        f"{render_dimension(declared.dimension)}，但方程右侧的量纲是 "
                        f"{render_dimension(right_dimension)}"
                    ),
                )
            declared_note = f"；声明结果单位 {declared_unit_raw!r} 与方程右侧一致"

        if left_dimension != right_dimension:
            return Verdict(
                status="fail",
                detail=(
                    f"方程两侧量纲不一致：左侧是 {render_dimension(left_dimension)}，"
                    f"右侧是 {render_dimension(right_dimension)}；"
                    f"等式 {equation_raw!r} 不成立"
                ),
            )

        symbols = _free_symbols(left) | _free_symbols(right)
        si_values = _si_values(symbols, units, values)
        left_value: float | None = None
        right_value: float | None = None
        if si_values is not None:
            left_value = _eval_node(left, si_values)
            right_value = _eval_node(right, si_values)
            if not math.isfinite(left_value) or not math.isfinite(right_value):
                raise _UnitError("方程某侧在给定数值下不是有限数")

        expected_failure = _check_expected(
            expected=expected,
            reference_dimension=right_dimension,
            reference_value=right_value,
            reference_label="方程右侧",
            tolerance=tolerance,
        )
        if expected_failure is not None:
            return expected_failure

        if left_value is None or right_value is None:
            missing = ", ".join(sorted(symbols - set(values)))
            return Verdict(
                status="pass",
                detail=(
                    f"量纲一致（{render_dimension(left_dimension)}）；"
                    f"缺少 {missing} 的数值，未做数值回代{declared_note}"
                ),
            )
        if not _numbers_agree(left_value, right_value, tolerance):
            return Verdict(
                status="fail",
                detail=(
                    f"数值回代不一致：左侧 {_fmt(left_value)}、右侧 {_fmt(right_value)}"
                    f"（{render_dimension(left_dimension)}），相差 "
                    f"{_fmt(abs(left_value - right_value))}，超过容差 "
                    f"({_tolerance_text(tolerance)})"
                ),
            )
        expected_note = ""
        if expected is not None:
            expected_note = "；声明结果值与单位一致"
        return Verdict(
            status="pass",
            detail=(
                f"量纲一致（{render_dimension(left_dimension)}）；数值回代通过："
                f"左侧 {_fmt(left_value)}、右侧 {_fmt(right_value)}，"
                f"差在容差内（{_tolerance_text(tolerance)}）{declared_note}{expected_note}"
            ),
        )

    if not isinstance(expression_raw, str):
        raise _UnitError("expression 必须是字符串")
    expression = _parse(expression_raw, "expression")
    expression_dimension = _dimension_node(expression, units)
    if not isinstance(declared_unit_raw, str):
        raise _UnitError("没有 equation 时，expression 必须配一个 unit 字符串")
    declared = parse_unit(declared_unit_raw)
    if declared.dimension != expression_dimension:
        return Verdict(
            status="fail",
            detail=(
                f"表达式量纲不一致：表达式是 {render_dimension(expression_dimension)}，"
                f"声明单位 {declared_unit_raw!r} 是 {render_dimension(declared.dimension)}"
            ),
        )

    symbols = _free_symbols(expression)
    si_values = _si_values(symbols, units, values)
    expression_value: float | None = None
    if si_values is not None:
        expression_value = _eval_node(expression, si_values)
        if not math.isfinite(expression_value):
            raise _UnitError("表达式在给定数值下不是有限数")

    expected_failure = _check_expected(
        expected=expected,
        reference_dimension=expression_dimension,
        reference_value=expression_value,
        reference_label="表达式",
        tolerance=tolerance,
    )
    if expected_failure is not None:
        return expected_failure

    if expression_value is None:
        missing = ", ".join(sorted(symbols - set(values)))
        return Verdict(
            status="pass",
            detail=(
                f"表达式量纲 {render_dimension(expression_dimension)} 与声明单位 "
                f"{declared_unit_raw!r} 一致；缺少 {missing} 的数值，未做数值回代"
            ),
        )
    expected_note = ""
    if expected is not None:
        expected_note = "；声明结果值与单位一致"
    return Verdict(
        status="pass",
        detail=(
            f"表达式量纲 {render_dimension(expression_dimension)} 与声明单位 "
            f"{declared_unit_raw!r} 一致；求值 {_fmt(expression_value)}（SI）"
            f"{expected_note}"
        ),
    )


def verify_step(step: StudentStep) -> Verdict:
    """Verify one physics step from its structured ``data``.

    Returns ``unknown`` when the payload is absent/incomplete/unreadable,
    ``fail`` for a concrete dimensional or numeric inconsistency, and ``pass``
    only for checks that actually ran. The function never executes Python code
    from the step and never raises for malformed student input.
    """

    try:
        return _verify_step(step)
    except _DimensionMismatch as exc:
        return Verdict(status="fail", detail=str(exc))
    except _UnitError as exc:
        return Verdict(status="unknown", detail=f"物理结构化步骤无法验证：{exc}")
    except (TypeError, KeyError, ArithmeticError, RecursionError) as exc:
        return Verdict(status="unknown", detail=f"物理结构化步骤无法验证：{exc}")
    except ValueError as exc:
        return Verdict(status="unknown", detail=f"物理结构化步骤无法验证：{exc}")


def verify_equation(
    equation: str,
    units: Mapping[str, str],
    values: Mapping[str, float] | None = None,
    tolerance: object = None,
    expected: Mapping[str, object] | None = None,
    unit: str | None = None,
) -> Verdict:
    """Convenience wrapper around :func:`verify_step` for a single equation.

    ``units`` maps each symbol to its unit expression; ``values`` is optional
    and is interpreted in those units. This keeps the public verifier API close
    to the data protocol without duplicating the checking logic.
    """

    data: dict[str, object] = {"equation": equation, "units": units}
    if values is not None:
        data["values"] = values
    if tolerance is not None:
        data["tolerance"] = tolerance
    if expected is not None:
        data["expected"] = expected
    if unit is not None:
        data["unit"] = unit
    return verify_step(StudentStep(node_id="", text="", data=data))
