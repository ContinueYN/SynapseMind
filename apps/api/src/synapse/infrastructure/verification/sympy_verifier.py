"""SymPy-backed falsifier for a graph's declared answer range (M2.5 S5).

The check is deliberately a *falsifier*, not a prover:

    claim:  ∀ x ∈ D:  f(x, a) rel 0        answer:  a ∈ S

Two directions are sampled, and one counterexample is enough to ``fail``:

- **soundness** — every sampled ``a ∈ S`` must satisfy the constraint. A
  violation is the classic "the range includes a value that does not work".
- **completeness** — every sampled ``a ∉ S`` must *break* the constraint. A
  value that satisfies it but is missing from the answer is the M2.5 S4
  failure: ``P_DERIV_003`` dropped ``a=0`` from ``[0, e]``.

The inner ∀ is decided numerically: a fixed grid over ``D`` (linear near the
origin, geometric across twelve decades, points crowding every finite boundary)
plus a golden-section refinement around the best sample. The grid is fixed so a
pathological expression costs the same as a normal one — no symbolic
``solveset``/``limit`` call can stall the request. When the search cannot
decide, the verdict is ``unknown``: downgrading to "not verified" is honest,
guessing is not.

Expressions come from a model, so parsing is sandboxed: a character whitelist,
a SymPy namespace with ``__builtins__`` removed, and a free-symbol check that
rejects anything except the declared variable and parameter (lowercase ``e`` is
read as Euler's number, and ``log_2(...)``-style bases are supported).
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Final

import sympy as sp
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

from synapse.application.verification import (
    CounterExample,
    VerificationResult,
    describe_claim,
)
from synapse.domain.problem.models import SolutionGraph, VerificationClaim

# --- search budget (fixed on purpose) ---------------------------------------
LINEAR_LOW: Final = -20.0
LINEAR_HIGH: Final = 20.0
LINEAR_STEP: Final = 0.1
GEOMETRIC_DECADES: Final = 12
GEOMETRIC_PER_DECADE: Final = 6
REFINE_ITERATIONS: Final = 48
TOLERANCE: Final = 1e-9
MAX_PARAMETER_SAMPLES: Final = 24
MAX_SCAN_POINTS: Final = 1200
MIN_ENDPOINT_OFFSET: Final = 1e-3

_RELATION_SYMBOLS = {"<=": "≤", ">=": "≥", "<": "<", ">": ">"}
_INFINITY_NAMES = {
    "inf": math.inf,
    "+inf": math.inf,
    "infinity": math.inf,
    "+infinity": math.inf,
    "oo": math.inf,
    "+oo": math.inf,
    "-inf": -math.inf,
    "-infinity": -math.inf,
    "-oo": -math.inf,
}
_ALLOWED_CHARACTERS = re.compile(r"^[0-9A-Za-z_+\-*/^().,\s]+$")
_INTERVAL_TEXT = re.compile(r"^\s*([(\[])\s*(.*?)\s*,\s*(.*?)\s*([)\]])$")

_TRANSFORMS = standard_transformations + (convert_xor, implicit_multiplication_application)


class _Unusable(Exception):
    """The claim cannot be read; the model must rewrite it (fail + retry)."""


class _Unsupported(Exception):
    """The claim is readable but outside v1 — recorded as unknown, never failed."""


@dataclass(frozen=True, slots=True)
class _Bounds:
    lower: float
    upper: float
    lower_inclusive: bool = True
    upper_inclusive: bool = True

    def contains(self, value: float) -> bool:
        if value < self.lower or value > self.upper:
            return False
        if value == self.lower and not self.lower_inclusive:
            return False
        return not (value == self.upper and not self.upper_inclusive)

    @property
    def unbounded(self) -> bool:
        return not math.isfinite(self.lower) and not math.isfinite(self.upper)


@dataclass(frozen=True, slots=True)
class _Program:
    claim: VerificationClaim
    domain: _Bounds
    answer: tuple[_Bounds, ...]
    grid: tuple[float, ...]
    evaluate: Callable[[float, float], float]
    summary: str


@dataclass(frozen=True, slots=True)
class _Scan:
    """What one parameter value did to the constraint."""

    kind: str  # "violated" | "holds" | "undecided"
    points: int = 0
    x: float = 0.0
    value: float = 0.0
    detail: str = ""


class SymPyVerifier:
    """Check a graph's ``claim`` and return ``pass``/``fail``/``unknown``."""

    def verify(self, graph: SolutionGraph) -> VerificationResult:
        claim = graph.claim
        if claim is None:
            return VerificationResult(
                status="unknown",
                reason="no_claim",
                detail="图没有 claim：答案不是可形式化的参数区间，本次不做数学验证",
            )
        try:
            program = _compile(claim)
        except _Unsupported as exc:
            return VerificationResult(status="unknown", reason="unsupported_kind", detail=str(exc))
        except _Unusable as exc:
            return VerificationResult(
                status="fail",
                reason="malformed",
                detail=f"claim 无法被验证器读取：{exc}",
            )

        inside = _inside_samples(program.answer)
        outside = _outside_samples(program.answer)

        counterexamples: list[CounterExample] = []
        undecided = 0
        parameter_samples = 0
        point_checks = 0

        for value in inside[:MAX_PARAMETER_SAMPLES]:
            parameter_samples += 1
            scan = _scan(program, value)
            point_checks += scan.points
            if scan.kind == "violated":
                counterexamples.append(
                    CounterExample(
                        parameter=claim.parameter,
                        parameter_value=_format_number(value),
                        variable=claim.variable,
                        variable_value=_format_number(scan.x),
                        detail=(
                            f"{program.summary}；但 a={_format_number(value)} 在答案区间内，"
                            f"x={_format_number(scan.x)} 时表达式={_format_number(scan.value)}，"
                            f"不满足 {_RELATION_SYMBOLS[claim.relation]}0 —— 答案区间偏宽"
                        ),
                    )
                )
            elif scan.kind == "undecided":
                undecided += 1

        for value in outside[:MAX_PARAMETER_SAMPLES]:
            parameter_samples += 1
            scan = _scan(program, value)
            point_checks += scan.points
            if scan.kind == "holds":
                counterexamples.append(
                    CounterExample(
                        parameter=claim.parameter,
                        parameter_value=_format_number(value),
                        variable=claim.variable,
                        detail=(
                            f"{program.summary}；a={_format_number(value)} 满足约束"
                            f"（在取样范围内找不到反例），但不在答案区间里 —— 答案漏掉了"
                            f"这个参数值，区间偏窄"
                        ),
                    )
                )
            elif scan.kind == "undecided":
                undecided += 1

        if counterexamples:
            first = counterexamples[0]
            extra = f"（共 {len(counterexamples)} 个反例）" if len(counterexamples) > 1 else ""
            return VerificationResult(
                status="fail",
                reason="counterexample",
                detail=first.detail + extra,
                counterexample=first,
                parameter_samples=parameter_samples,
                point_checks=point_checks,
            )

        coverage = f"内点 {len(inside)} / 外点 {len(outside)} 个参数样本，{point_checks} 次取值"
        if undecided:
            return VerificationResult(
                status="unknown",
                reason="undecidable",
                detail=(
                    f"{coverage}，其中 {undecided} 个样本在定义域上无定义或落在容差带内，"
                    "无法判定（未发现反例，也未证明）"
                ),
                parameter_samples=parameter_samples,
                point_checks=point_checks,
            )
        if not outside:
            return VerificationResult(
                status="pass",
                reason="ok",
                detail=f"{coverage}；答案覆盖整个实轴，没有外部点可检查（完备性无从证伪）",
                parameter_samples=parameter_samples,
                point_checks=point_checks,
            )
        return VerificationResult(
            status="pass",
            reason="ok",
            detail=f"{coverage}，两个方向都未发现反例",
            parameter_samples=parameter_samples,
            point_checks=point_checks,
        )


# --- compilation ------------------------------------------------------------


def _parser_namespace() -> dict[str, object]:
    """SymPy's namespace without the builtins ``sympify`` would otherwise expose."""
    namespace: dict[str, object] = {
        key: value for key, value in vars(sp).items() if not key.startswith("__")
    }
    namespace["__builtins__"] = {}
    for name in ("eval", "exec", "open", "compile", "input", "breakpoint", "print"):
        namespace.pop(name, None)
    return namespace


_NAMESPACE = _parser_namespace()


def _parse(
    text: str,
    local: dict[str, object] | None = None,
) -> sp.Expr:
    if not _ALLOWED_CHARACTERS.fullmatch(text):
        raise _Unusable(f"{text!r} 含不支持的字符（只允许数字、字母、+ - * / ^ ( ) . ,）")
    try:
        expr = parse_expr(
            text,
            local_dict=dict(local or {}),
            global_dict=_NAMESPACE,
            transformations=_TRANSFORMS,
            evaluate=True,
        )
    except Exception as exc:  # noqa: BLE001 - every parser failure is the same "unusable"
        raise _Unusable(f"{text!r} 无法解析（{exc}）") from exc
    if not isinstance(expr, sp.Expr):
        raise _Unusable(f"{text!r} 不是数学表达式")
    return expr


def _euler(expr: sp.Expr) -> sp.Expr:
    """Read a bare lowercase ``e`` as Euler's number, as students write it."""
    return expr.subs(sp.Symbol("e"), sp.E)


def _parse_constraint(
    claim: VerificationClaim,
) -> tuple[sp.Expr, sp.Symbol, sp.Symbol, Callable[[float, float], float]]:
    variable = sp.Symbol(claim.variable, real=True)
    parameter = sp.Symbol(claim.parameter, real=True)
    local: dict[str, object] = {claim.variable: variable, claim.parameter: parameter}
    for base in range(2, 11):
        local[f"log_{base}"] = _log_base(base)

    expr = _euler(_parse(claim.expression, local))
    unknown = expr.free_symbols - {variable, parameter}
    if unknown:
        names = "、".join(sorted(str(symbol) for symbol in unknown))
        raise _Unusable(
            f"表达式里出现了未声明的符号：{names}（只允许 {claim.variable} 与 {claim.parameter}）"
        )
    return expr, variable, parameter, sp.lambdify((variable, parameter), expr, modules=["math"])


def _log_base(base: int) -> Callable[[sp.Expr], sp.Expr]:
    def logarithm(value: sp.Expr) -> sp.Expr:
        return sp.log(value, base)

    return logarithm


def _constant(text: str) -> float:
    if not text.strip():
        raise _Unusable("端点为空")
    expr = _euler(_parse(text.strip()))
    if expr.free_symbols:
        names = "、".join(sorted(str(symbol) for symbol in expr.free_symbols))
        raise _Unusable(f"端点 {text!r} 含未声明的符号：{names}（端点必须是常数）")
    if expr in (sp.oo, -sp.oo):
        return math.inf if expr is sp.oo else -math.inf
    try:
        number = float(sp.N(expr, 24))
    except (TypeError, ValueError) as exc:
        raise _Unusable(f"端点 {text!r} 不是实数") from exc
    if math.isnan(number):
        raise _Unusable(f"端点 {text!r} 不是有限实数")
    return number


def _bound(text: str, *, lower: bool) -> float:
    normalised = (
        text.strip()
        .lower()
        .replace(" ", "")
        .replace("∞", "inf")
        .replace("−", "-")
        .replace("+infinity", "+inf")
        .replace("-infinity", "-inf")
    )
    if normalised in _INFINITY_NAMES:
        value = _INFINITY_NAMES[normalised]
        if lower and value > 0:
            raise _Unusable("下端点不能是 +∞")
        if not lower and value < 0:
            raise _Unusable("上端点不能是 −∞")
        return value
    return _constant(text)


def _parse_domain(text: str) -> _Bounds:
    if "∪" in text:
        raise _Unusable("变量定义域必须是单个区间（不能是并集）")
    match = _INTERVAL_TEXT.match(text)
    if match is None:
        raise _Unusable(f"变量定义域 {text!r} 不是区间写法（如 (0,+inf)、[1,3]）")
    opening, raw_low, raw_high, closing = match.groups()
    lower = _bound(raw_low, lower=True)
    upper = _bound(raw_high, lower=False)
    if not lower < upper:
        raise _Unusable(f"变量定义域 {text!r} 是空的")
    if not math.isfinite(lower) and opening != "(":
        raise _Unusable(f"变量定义域 {text!r}：−∞ 一侧必须用圆括号")
    if not math.isfinite(upper) and closing != ")":
        raise _Unusable(f"变量定义域 {text!r}：+∞ 一侧必须用圆括号")
    return _Bounds(
        lower=lower,
        upper=upper,
        lower_inclusive=opening == "[",
        upper_inclusive=closing == "]",
    )


def _answer(claim: VerificationClaim) -> tuple[_Bounds, ...]:
    intervals: list[_Bounds] = []
    for index, interval in enumerate(claim.intervals, start=1):
        lower = -math.inf if interval.lower is None else _bound(interval.lower, lower=True)
        upper = math.inf if interval.upper is None else _bound(interval.upper, lower=False)
        if lower > upper:
            raise _Unusable(
                f"第 {index} 个区间的下端点 {_format_number(lower)} "
                f"大于上端点 {_format_number(upper)}"
            )
        intervals.append(
            _Bounds(
                lower=lower,
                upper=upper,
                # An unbounded side is always open: there is no endpoint to include.
                lower_inclusive=interval.lower_inclusive and math.isfinite(lower),
                upper_inclusive=interval.upper_inclusive and math.isfinite(upper),
            )
        )
    intervals.sort(key=lambda bounds: (bounds.lower, bounds.upper))
    for previous, current in zip(intervals, intervals[1:], strict=False):
        if current.lower < previous.upper or (
            current.lower == previous.upper and previous.upper_inclusive and current.lower_inclusive
        ):
            raise _Unusable(
                f"答案区间重叠或相接：{_render_bounds(previous)} 与 "
                f"{_render_bounds(current)}；请合并成一个区间"
            )
    return tuple(intervals)


def _compile(claim: VerificationClaim) -> _Program:
    if claim.kind != "parameter_range":
        raise _Unsupported(
            f"claim.kind={claim.kind!r} 不在 v1 支持范围内（只支持 parameter_range）"
        )
    if claim.relation not in _RELATION_SYMBOLS:
        raise _Unsupported(f"关系符 {claim.relation!r} 不在 v1 支持范围内（只支持 <=、>=、<、>）")
    if not claim.intervals:
        raise _Unusable("claim 没有给出答案区间")
    expr, variable, parameter, evaluate = _parse_constraint(claim)
    del variable, parameter
    domain = _parse_domain(claim.variable_domain)
    answer = _answer(claim)
    return _Program(
        claim=claim,
        domain=domain,
        answer=answer,
        grid=_x_grid(domain),
        evaluate=evaluate,
        summary=describe_claim(claim),
    )


# --- sampling ---------------------------------------------------------------


def _x_grid(domain: _Bounds) -> tuple[float, ...]:
    candidates: set[float] = set()

    low = max(domain.lower, LINEAR_LOW) if math.isfinite(domain.lower) else LINEAR_LOW
    high = min(domain.upper, LINEAR_HIGH) if math.isfinite(domain.upper) else LINEAR_HIGH
    if high > low:
        steps = min(int((high - low) / LINEAR_STEP), MAX_SCAN_POINTS // 2)
        for index in range(steps + 1):
            candidates.add(round(low + index * LINEAR_STEP, 12))

    for decade in range(-GEOMETRIC_DECADES, GEOMETRIC_DECADES + 1):
        centre = 10.0**decade
        for step in range(GEOMETRIC_PER_DECADE):
            factor = 10.0 ** (step / GEOMETRIC_PER_DECADE)
            candidates.add(centre * factor)
            candidates.add(-centre * factor)

    # Crowd every finite boundary from the inside; divergence at an open end
    # (log x → −∞ at 0+) is exactly where a wrong range shows up.
    for edge, sign in ((domain.lower, 1.0), (domain.upper, -1.0)):
        if math.isfinite(edge):
            scale = max(1.0, abs(edge))
            for offset in (1e-12, 1e-9, 1e-6, 1e-3, 1e-2):
                candidates.add(edge + sign * offset * scale)
            if domain.contains(edge):
                candidates.add(edge)

    grid = sorted(value for value in candidates if math.isfinite(value) and domain.contains(value))
    return tuple(grid[:MAX_SCAN_POINTS])


def _inside_samples(answer: tuple[_Bounds, ...]) -> list[float]:
    values: list[float] = []
    for bounds in answer:
        low, high = bounds.lower, bounds.upper
        if math.isfinite(low) and math.isfinite(high):
            width = high - low
            if width == 0:
                values.append(low)
                continue
            start = (
                low if bounds.lower_inclusive else low + MIN_ENDPOINT_OFFSET * max(1.0, abs(low))
            )
            end = (
                high if bounds.upper_inclusive else high - MIN_ENDPOINT_OFFSET * max(1.0, abs(high))
            )
            values += [start, start + width * 0.25, (start + end) / 2, start + width * 0.75, end]
        elif math.isfinite(low):
            start = (
                low if bounds.lower_inclusive else low + MIN_ENDPOINT_OFFSET * max(1.0, abs(low))
            )
            scale = max(1.0, abs(start))
            values += [
                start,
                start + 1e-3 * scale,
                start + 0.5 * scale,
                start + scale,
                start + 3 * scale,
                start + 10 * scale,
            ]
        elif math.isfinite(high):
            start = (
                high if bounds.upper_inclusive else high - MIN_ENDPOINT_OFFSET * max(1.0, abs(high))
            )
            scale = max(1.0, abs(start))
            values += [
                start,
                start - 1e-3 * scale,
                start - 0.5 * scale,
                start - scale,
                start - 3 * scale,
                start - 10 * scale,
            ]
        else:
            values += [-100.0, -10.0, -1.0, -0.5, 0.0, 0.5, 1.0, 10.0, 100.0]
    return _unique(value for value in values if any(part.contains(value) for part in answer))


def _outside_samples(answer: tuple[_Bounds, ...]) -> list[float]:
    values: list[float] = []
    for bounds in answer:
        for edge, inside in (
            (bounds.lower, bounds.lower_inclusive),
            (bounds.upper, bounds.upper_inclusive),
        ):
            if not math.isfinite(edge):
                continue
            offset = max(MIN_ENDPOINT_OFFSET, abs(edge) * MIN_ENDPOINT_OFFSET)
            if not inside:
                values.append(edge)  # the excluded endpoint itself: the a=0 case
            values += [edge - offset, edge + offset, edge - 1.0, edge + 1.0]

    for previous, current in zip(answer, answer[1:], strict=False):
        if math.isfinite(previous.upper) and math.isfinite(current.lower):
            gap = current.lower - previous.upper
            if gap > 0:
                values += [
                    previous.upper + gap * 0.25,
                    previous.upper + gap / 2,
                    previous.upper + gap * 0.75,
                ]

    if math.isfinite(answer[0].lower):
        values += [answer[0].lower - 1.0, answer[0].lower - 10.0]
    if math.isfinite(answer[-1].upper):
        values += [answer[-1].upper + 1.0, answer[-1].upper + 10.0]

    # Fixed probes catch a range that is wrong far from any endpoint.
    values += [-1e6, -1e3, -1.0, 0.0, 1.0, 1e3, 1e6]
    return _unique(value for value in values if not any(part.contains(value) for part in answer))


def _unique(values: Iterable[float]) -> list[float]:
    seen: set[float] = set()
    result: list[float] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return sorted(result)


# --- one parameter value ----------------------------------------------------


def _scan(program: _Program, parameter: float) -> _Scan:
    """Minimise the *slack* of the constraint, not the expression.

    For ``f ≥ 0`` the slack is ``f`` (a negative value is a violation); for
    ``f ≤ 0`` it is ``-f``, so the search must maximise ``f``. Getting this
    backwards makes ``ln x + 10⁶x ≤ 0`` look satisfied.
    """
    sign = 1.0 if program.claim.relation in (">=", ">") else -1.0

    def slack_at(x: float, value: float) -> float:
        return sign * value

    points: list[tuple[float, float]] = []
    skipped = 0
    for x in program.grid:
        raw = _evaluate(program.evaluate, x, parameter)
        if raw is None:
            skipped += 1
            continue
        points.append((x, slack_at(x, raw)))
    if not points:
        return _Scan("undecided", detail="定义域内没有可计算的取样点")
    if skipped > len(program.grid) // 2:
        return _Scan("undecided", points=len(points), detail="超过一半的取样点无定义")

    best_x, slack = min(points, key=lambda item: item[1])
    bracket = _bracket(program.grid, best_x, program.domain)
    if bracket is not None:
        refined = _golden_section(_slack_evaluator(program.evaluate, sign), bracket, parameter)
        if refined is not None and refined[1] < slack:
            best_x, slack = refined

    witness = sign * slack
    if slack < -TOLERANCE:
        return _Scan("violated", points=len(points), x=best_x, value=witness)
    if slack > TOLERANCE:
        return _Scan("holds", points=len(points), x=best_x, value=witness)
    # Exactly on the boundary: fine for ≤/≥, undecidable for strict relations.
    if program.claim.relation in (">", "<"):
        return _Scan("undecided", points=len(points), x=best_x, value=witness)
    return _Scan("holds", points=len(points), x=best_x, value=witness)


def _slack_evaluator(
    evaluate: Callable[[float, float], float],
    sign: float,
) -> Callable[[float, float], float]:
    def signed(x: float, parameter: float) -> float:
        return sign * evaluate(x, parameter)

    return signed


def _evaluate(
    evaluate: Callable[[float, float], float], x: float, parameter: float
) -> float | None:
    try:
        value = float(evaluate(x, parameter))
    except (ValueError, ZeroDivisionError, OverflowError, TypeError):
        return None
    if math.isnan(value):
        return None
    return value


def _bracket(grid: tuple[float, ...], x: float, domain: _Bounds) -> tuple[float, float] | None:
    index = grid.index(x) if x in grid else None
    if index is None:
        return None
    low = grid[index - 1] if index > 0 else x
    high = grid[index + 1] if index + 1 < len(grid) else x
    if low == high:
        return None
    if not (domain.contains(low) and domain.contains(high)):
        return None
    return (low, high)


def _golden_section(
    evaluate: Callable[[float, float], float],
    bracket: tuple[float, float],
    parameter: float,
) -> tuple[float, float] | None:
    """Minimise the sampled expression inside a grid bracket."""
    low, high = bracket
    ratio = (math.sqrt(5.0) - 1.0) / 2.0
    left, right = low, high
    c = right - ratio * (right - left)
    d = left + ratio * (right - left)
    fc = _evaluate(evaluate, c, parameter)
    fd = _evaluate(evaluate, d, parameter)
    for _ in range(REFINE_ITERATIONS):
        if fc is None or fd is None:
            return None
        if fc < fd:
            right, d, fd = d, c, fc
            c = right - ratio * (right - left)
            fc = _evaluate(evaluate, c, parameter)
        else:
            left, c, fc = c, d, fd
            d = left + ratio * (right - left)
            fd = _evaluate(evaluate, d, parameter)
    if fc is not None and (fd is None or fc <= fd):
        return (c, fc)
    if fd is not None:
        return (d, fd)
    return None


# --- rendering --------------------------------------------------------------


def _format_number(value: float) -> str:
    if value == math.inf:
        return "+∞"
    if value == -math.inf:
        return "−∞"
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return f"{value:.10g}"


def _render_bounds(bounds: _Bounds) -> str:
    left = "[" if bounds.lower_inclusive else "("
    right = "]" if bounds.upper_inclusive else ")"
    return f"{left}{_format_number(bounds.lower)}, {_format_number(bounds.upper)}{right}"
