"""把学生的中式数学写法转成 SymPy 能读的表达式。

存在性对齐只会说「这步没看到」；要回答「这一步错哪了」，得先让机器读懂学生
写的式子。学生写的是 `2x`、`x²`、`根号（245*80）`、`sinX/x`，SymPy 只认
`2*x`、`x**2`、`sqrt(245*80)`、`sin(x)/x`。

这个模块只做**机械转写**，不做语义猜测：认不出来就返回 ``None``，由调用方
记 ``notation_unsupported``。猜错的代价是给学生的诊断是假的，宁可不说话。
"""

from __future__ import annotations

import re
from typing import Any

# 全角/符号：先换符号再换上下标，顺序不能反（`²` 换完还要走一遍乘法）。
_SYMBOLS = {
    "（": "(",
    "）": ")",
    "［": "[",
    "］": "]",
    "，": ",",
    "＝": "=",
    "＋": "+",
    "－": "-",
    "−": "-",
    "—": "-",
    "×": "*",
    "·": "*",
    "÷": "/",
    "／": "/",
    "＜": "<",
    "＞": ">",
    "≤": "<=",
    "≥": ">=",
    "π": "pi",
    "√": "sqrt",
    "²": "**2",
    "³": "**3",
    "⁴": "**4",
}

_ALLOWED = {
    "sin",
    "cos",
    "tan",
    "log",
    "ln",
    "sqrt",
    "abs",
    "exp",
    "pi",
}

_FUNCTION_CALL = re.compile(r"(?<![a-z])(sin|cos|tan|log|sqrt|abs|exp)\s*([a-z])")
_IMPLICIT_DIGIT = re.compile(r"(\d)\s*([a-z(])")
_IMPLICIT_PAREN = re.compile(r"\)\s*(\d|[a-z](?![a-z])|\()")
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def normalize(source: str) -> str:
    """`sinX/x²` → `sin(x)/x**2`；不做语义判断，只做字符级改写。"""

    text = source
    for old, new in _SYMBOLS.items():
        text = text.replace(old, new)
    text = text.replace("根号", "sqrt").replace("ln", "log")
    # 学生常把自变量写成大写 X；函数名已经替换完，这里统一成小写。
    text = text.replace("X", "x")
    text = _FUNCTION_CALL.sub(r"\1(\2)", text)
    text = _IMPLICIT_DIGIT.sub(r"\1*\2", text)
    text = _IMPLICIT_PAREN.sub(r")*\1", text)
    return re.sub(r"\s+", "", text)


def _identifiers_ok(text: str) -> bool:
    for name in _IDENTIFIER.findall(text):
        if len(name) == 1:
            continue
        if name in _ALLOWED:
            continue
        return False
    return True


def parse(source: str) -> Any | None:
    """转写并解析成 SymPy 表达式；任何一处不确定都返回 ``None``。"""

    if not source or not source.strip():
        return None
    text = normalize(source)
    if not text:
        return None
    # 还有中文（`h台`、`有哪里错了么`）就说明这不是纯式子，不猜。
    if any(ord(ch) > 127 for ch in text):
        return None
    if not _identifiers_ok(text):
        return None
    try:
        import sympy
        from sympy.parsing.sympy_parser import (
            convert_xor,
            parse_expr,
            standard_transformations,
        )
    except ImportError:  # pragma: no cover - SymPy 是 [dev] extra
        return None
    local: dict[str, Any] = {
        "sin": sympy.sin,
        "cos": sympy.cos,
        "tan": sympy.tan,
        "log": sympy.log,
        "sqrt": sympy.sqrt,
        "abs": sympy.Abs,
        "exp": sympy.exp,
        "pi": sympy.pi,
    }
    # parse_expr 内部还要用到 Symbol/Integer 等名字，所以 global_dict 不能只剩
    # __builtins__；但必须把 __builtins__ 置空，杜绝 eval 层面的逃逸。
    global_dict: dict[str, Any] = {
        name: value for name, value in vars(sympy).items() if not name.startswith("_")
    }
    global_dict["__builtins__"] = {}
    try:
        value = parse_expr(
            text,
            local_dict=local,
            global_dict=global_dict,
            transformations=standard_transformations + (convert_xor,),
            evaluate=True,
        )
    except Exception:  # noqa: BLE001 - 任何解析失败都只是「读不懂」
        return None
    return value


def free_symbols(expression: Any) -> set[str]:
    try:
        return {str(symbol) for symbol in expression.free_symbols}
    except Exception:  # noqa: BLE001
        return set()
