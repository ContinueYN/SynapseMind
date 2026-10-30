"""学生自己写的等号链，机器能判它对不对（M2.5 S5 ⑥，2026-10-30 深夜）。

存在性对齐只能回答「这步有没有写到」。可学生真正问的是「我错哪了」——而学生
的错最常见就落在他自己写的一个等号上：`sinx/(x+tanx) = sinx/x + tanx/x`。
这条等式不成立，不需要参考答案就能判：两边作为 x 的函数不等价。

所以这里只做一件事：把学生过程里的 `A = B = C` 链拆出来，逐对判等号。

* **普通链**：两边都读得懂、自由符号集合相同、且都不是单个符号（单个符号的
  `an = 3^(n-1)` 是定义不是断言）→ 用 `simplify(A-B)==0` 判等价，不等价就
  找一个具体反例。
* **极限链**（出现 `lim`）：`=1+1` 这种是「在极限下相等」，直接判等价会误报，
  于是改判**两边的极限是否相等**（默认 x→0，链里写了 `x→1` 就按它）。

判不了就说判不了：读不懂的写法（`h台/h锥`）整段跳过，记 `notation_unsupported`。
**宁可漏判，不误判**——把学生正确的一步判成错，比不判更伤。

``SympyEqualityChecker`` 是这个模块对外的端口适配器；产品链路只认
``application.work_check.EqualityChecker``，不直接 import 这个模块。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from synapse.domain.diagnosis.work import WorkFinding
from synapse.infrastructure.verification.notation import free_symbols, normalize, parse

_SEGMENT_SPLIT = re.compile(r"[。；;\n]+")
# 提取「式子」时允许出现的字符；中文一律不属于式子，遇到就断。
_FORMULA = re.compile(r"[0-9A-Za-z+\-*/^().\[\]{} ]+")
_LIMIT_AT = re.compile(r"[xX]\s*(?:→|->|=>)\s*(-?\d+(?:\.\d+)?)")
# 式子两侧的虚词：删掉不影响数学含义，留着会让整段读不懂。
_NOISE = ("所以", "因为", "根号下", "即", "则", "故", "约", "下", "的", "得", "为", "是", "有")
_SAMPLES = (0.1, 0.3, 0.7, 1.0, 1.7, 2.3, 3.7, 5.0, -0.4, -1.3)


@dataclass
class Report:
    chains: int = 0
    checked: int = 0
    findings: list[WorkFinding] = field(default_factory=list)
    skipped: dict[str, int] = field(default_factory=dict)

    def skip(self, reason: str) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + 1


@dataclass(frozen=True, slots=True)
class _Piece:
    raw: str  # 归一化后、去掉虚词的片段（可能为空 = 这一侧没式子）
    body: str  # 去掉 lim 外壳后拿去解析的式子
    is_limit: bool


def _strip_limit(raw: str) -> tuple[str, bool]:
    """去掉 `lim`/`lim_{x→0}`/`lim[...]` 外壳，返回（式子, 是否极限）。"""

    text = raw.strip()
    if "lim" not in text.lower():
        return text, False
    text = re.sub(r"(?i)lim", " ", text)
    text = re.sub(r"(?i)_\s*\{[^}]*\}", " ", text)  # lim_{x→0}
    text = text.replace("→", " ").replace("_", " ")
    text = text.replace("[", "(").replace("]", ")")
    return text.strip(), True


def _drop_noise(text: str) -> str:
    for word in _NOISE:
        text = text.replace(word, " ")
    return text


def _pieces(segment: str) -> list[_Piece]:
    """把一段按 `=` 拆成片段；每个片段取其中最长的「式子」子串。"""

    text = _drop_noise(normalize(segment))
    pieces: list[_Piece] = []
    for part in re.split(r"[=＝]", text):
        longest = ""
        for match in _FORMULA.finditer(part):
            if len(match.group(0).strip()) > len(longest.strip()):
                longest = match.group(0)
        raw = longest.strip()
        body, is_limit = _strip_limit(raw)
        pieces.append(_Piece(raw=raw, body=body, is_limit=is_limit))
    return pieces


def _numeric(value: Any) -> float | None:
    try:
        number = complex(value)
    except (TypeError, ValueError):
        return None
    if abs(number.imag) > 1e-9:
        return None
    return float(number.real)


def _limit_of(expression: Any, variable: Any, point: float) -> Any | None:
    import sympy

    try:
        return sympy.limit(expression, variable, point)
    except Exception:  # noqa: BLE001 - 极限算不出来只是「判不了」
        return None


def _identity_verdict(left: Any, right: Any, symbols: set[str]) -> tuple[bool | None, str]:
    """等价 → True；举出反例 → False；说不清 → None。"""

    import sympy

    try:
        if sympy.simplify(left - right) == 0:
            return True, ""
    except Exception:  # noqa: BLE001
        return None, ""
    names = sorted(symbols)
    if len(names) != 1:
        return None, ""
    symbol = sympy.Symbol(names[0])
    for sample in _SAMPLES:
        try:
            a = _numeric(left.subs(symbol, sample))
            b = _numeric(right.subs(symbol, sample))
        except Exception:  # noqa: BLE001
            continue
        if a is None or b is None:
            continue
        if abs(a - b) > 1e-6:
            return False, f"{names[0]}={sample:g} 时左边 {a:.4g}、右边 {b:.4g}"
    return None, ""


def _check_pair(left: _Piece, right: _Piece, *, limit_point: float | None, report: Report) -> None:
    left_expr = parse(left.body)
    right_expr = parse(right.body)
    if left_expr is None or right_expr is None:
        report.skip("notation_unsupported")
        return
    symbols = free_symbols(left_expr) | free_symbols(right_expr)

    # 纯数字：`1+1 = 2` 直接比数值。
    if not symbols:
        a, b = _numeric(left_expr), _numeric(right_expr)
        if a is None or b is None:
            report.skip("not_numeric")
            return
        report.checked += 1
        if abs(a - b) > 1e-9:
            summary = f"左边 {a:.6g}、右边 {b:.6g}"
            report.findings.append(
                WorkFinding(
                    kind="identity",
                    left=left.body,
                    right=right.body,
                    detail="这个等号不成立。",
                    counterexample=f"左边 {a:.6g}，右边 {b:.6g}",
                    summary=summary,
                )
            )
        return

    if limit_point is not None and (left.is_limit or right.is_limit):
        import sympy

        name = sorted(symbols)[0]
        variable = sympy.Symbol(name)
        left_value = _limit_of(left_expr, variable, limit_point)
        right_value = _limit_of(right_expr, variable, limit_point)
        if left_value is None or right_value is None:
            report.skip("limit_unknown")
            return
        a, b = _numeric(left_value), _numeric(right_value)
        if a is None or b is None:
            report.skip("limit_unknown")
            return
        report.checked += 1
        if abs(a - b) > 1e-6:
            report.findings.append(
                WorkFinding(
                    kind="limit",
                    left=left.body,
                    right=right.body,
                    detail=(f"这个等号不成立：{name}→{limit_point:g} 时两边极限不同。"),
                    counterexample=f"左边极限 {a:.6g}，右边极限 {b:.6g}",
                    # 卡面直接用这一句：`x→0 时左边极限 0.5、右边 2`。
                    summary=(f"{name}→{limit_point:g} 时左边极限 {a:.6g}、右边 {b:.6g}"),
                )
            )
        return

    # 普通链：一侧没有自由符号，就是「解出来一个值」或「赋值」，判不了等价。
    if not free_symbols(left_expr) or not free_symbols(right_expr):
        report.skip("assignment_or_constant")
        return
    verdict, example = _identity_verdict(left_expr, right_expr, symbols)
    if verdict is None:
        report.skip("indeterminate")
        return
    report.checked += 1
    if verdict is False:
        report.findings.append(
            WorkFinding(
                kind="identity",
                left=left.body,
                right=right.body,
                detail="这个等号不成立：两边作为变量的函数不等价。",
                counterexample=example,
                summary=example,
            )
        )


def check_work(text: str) -> Report:
    """扫一遍学生过程，返回能被机器证明的「等号不成立」。"""

    report = Report()
    for segment in _SEGMENT_SPLIT.split(text or ""):
        if "=" not in segment and "＝" not in segment:
            continue
        pieces = _pieces(segment)
        if sum(1 for piece in pieces if piece.raw) < 2:
            continue
        report.chains += 1
        point: float | None = 0.0 if any(piece.is_limit for piece in pieces) else None
        match = _LIMIT_AT.search(segment)
        if point is not None and match is not None:
            point = float(match.group(1))
        for left, right in zip(pieces, pieces[1:], strict=False):
            if not left.raw or not right.raw:
                continue
            if not left.body or not right.body:
                report.skip("notation_unsupported")
                continue
            _check_pair(left, right, limit_point=point, report=report)
    return report


class SympyEqualityChecker:
    """Port adapter used by ``SessionService`` when the feature flag is on.

    SymPy is an optional extra: a deployment without it must still start
    sessions. Missing SymPy means "cannot judge", which is an empty finding
    list — never an exception and never a guess.
    """

    def findings(self, work: str) -> tuple[WorkFinding, ...]:
        try:
            return tuple(check_work(work).findings)
        except ImportError:
            return ()
