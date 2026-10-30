"""M2.5 S6 follow-up: the physics PARTIAL step verifier.

The verifier is a falsifier, not a physics prover. These tests pin down the
three honest outcomes:

* ``pass``  -- the checks that ran found no inconsistency (dimension-only when
               values are missing, dimension + numeric replay when they exist);
* ``fail``  -- a concrete dimension mismatch or numeric contradiction;
* ``unknown`` -- the structured payload is absent, incomplete, unreadable, or
               uses a unit/symbol/function outside the supported table.

The security tests matter because ``StudentStep`` data is student input. The
parser must reject Python syntax instead of executing it.
"""

from __future__ import annotations

import pytest

from synapse.application.subject import StudentStep
from synapse.infrastructure.subjects.physics import PhysicsPlugin
from synapse.infrastructure.verification.physics_units import (
    dimension_of,
    evaluate,
    parse_unit,
    render_dimension,
    verify_equation,
)

PLUGIN = PhysicsPlugin()


def _verdict(data: object) -> str:
    verdict = PLUGIN.verify(StudentStep(node_id="n2", text="", data=data))  # type: ignore[arg-type]
    return verdict.status


def _detail(data: object) -> str:
    verdict = PLUGIN.verify(StudentStep(node_id="n2", text="", data=data))  # type: ignore[arg-type]
    return verdict.detail


FORCE_EQUATION = {
    "equation": "F*cos(theta) - mu*N = m*a",
    "units": {
        "F": "N",
        "theta": "deg",
        "mu": "",
        "N": "N",
        "m": "kg",
        "a": "m/s^2",
    },
    "values": {
        "F": 10,
        "theta": 60,
        "mu": 0.2,
        "N": 10,
        "m": 2,
        "a": 1.5,
    },
}


def test_verify_equation_public_helper_matches_the_step_protocol() -> None:
    verdict = verify_equation(
        "F*cos(theta) - mu*N = m*a",
        FORCE_EQUATION["units"],
        values=FORCE_EQUATION["values"],
        expected={"value": 3, "unit": "N"},
    )

    assert verdict.status == "pass"
    assert "数值回代通过" in verdict.detail


def test_a_consistent_equation_passes_with_numbers() -> None:
    detail = _detail(FORCE_EQUATION)

    assert "量纲一致" in detail
    assert "数值回代通过" in detail
    assert "kg·m/s^2" in detail


def test_a_dimensionally_wrong_equation_fails_with_both_sides() -> None:
    data = {
        "equation": "F = q/E",
        "units": {"F": "N", "q": "C", "E": "N/C"},
        "values": {"F": 1, "q": 1, "E": 1},
    }

    detail = _detail(data)

    assert "量纲不一致" in detail
    assert "左侧" in detail
    assert "右侧" in detail
    # F is a force; q/E is C^2/N, not a force.
    assert "kg·m/s^2" in detail


def test_adding_incompatible_units_fails_instead_of_becoming_unknown() -> None:
    data = {"equation": "F + m = 0", "units": {"F": "N", "m": "kg"}}

    detail = _detail(data)

    assert "量纲不一致" in detail
    assert "加法" in detail


def test_a_dimensionally_correct_electric_equation_passes() -> None:
    data = {
        "equation": "F = q*E",
        "units": {"F": "N", "q": "C", "E": "N/C"},
        "values": {"F": 6, "q": 2, "E": 3},
    }

    assert _verdict(data) == "pass"
    assert "数值回代通过" in _detail(data)


def test_a_numeric_contradiction_fails_even_when_units_match() -> None:
    data = dict(FORCE_EQUATION)
    data["values"] = {**FORCE_EQUATION["values"], "a": 2.0}

    detail = _detail(data)

    assert "数值回代不一致" in detail
    assert "3" in detail and "4" in detail
    assert "超过容差" in detail


def test_an_equation_can_declare_the_result_unit_and_expected_value() -> None:
    data = dict(FORCE_EQUATION)
    data["unit"] = "N"
    data["expected"] = {"value": 3, "unit": "N"}

    detail = _detail(data)

    assert "量纲一致" in detail
    assert "声明结果值与单位一致" in detail


def test_an_equation_result_unit_mismatch_fails() -> None:
    data = dict(FORCE_EQUATION)
    data["unit"] = "m/s^2"

    assert _verdict(data) == "fail"
    assert "声明结果单位" in _detail(data)


def test_dimension_only_inspection_is_a_pass_with_an_explicit_gap() -> None:
    data = dict(FORCE_EQUATION)
    data.pop("values")

    detail = _detail(data)

    assert "量纲一致" in detail
    assert "未做数值回代" in detail
    assert "缺少" in detail


def test_missing_units_are_unknown_not_a_guess() -> None:
    data = {"equation": "F = m*a", "units": {"m": "kg", "a": "m/s^2"}}

    status = _verdict(data)
    detail = _detail(data)

    assert status == "unknown"
    assert "F" in detail
    assert "单位" in detail


def test_an_unknown_unit_name_is_unknown() -> None:
    data = {
        "equation": "F = m*a",
        "units": {"F": "newton", "m": "kg", "a": "m/s^2"},
    }

    assert _verdict(data) == "unknown"
    assert "newton" in _detail(data)


def test_a_pure_text_step_stays_unknown() -> None:
    verdict = PLUGIN.verify(StudentStep(node_id="n2", text="Fcos30° - μN = ma"))

    assert verdict.status == "unknown"
    assert "PARTIAL" in verdict.detail
    assert "data" in verdict.detail


def test_an_empty_payload_is_unknown() -> None:
    assert _verdict({}) == "unknown"
    assert "equation" in _detail({})


def test_equation_and_expression_together_are_ambiguous() -> None:
    data = {"equation": "1 = 1", "expression": "1", "unit": ""}

    assert _verdict(data) == "unknown"
    assert "不能同时" in _detail(data)


def test_expression_with_an_expected_result_passes() -> None:
    data = {
        "expression": "v",
        "unit": "m/s",
        "units": {"v": "m/s"},
        "values": {"v": 5},
        "expected": {"value": 18, "unit": "km/h"},
    }

    detail = _detail(data)

    assert "表达式量纲" in detail
    assert "声明结果值与单位一致" in detail


def test_an_expected_result_with_the_wrong_value_fails() -> None:
    data = {
        "expression": "v",
        "unit": "m/s",
        "units": {"v": "m/s"},
        "values": {"v": 5},
        "expected": {"value": 20, "unit": "km/h"},
    }

    detail = _detail(data)

    assert "结果值不一致" in detail
    assert "超过容差" in detail


def test_an_expected_result_with_the_wrong_unit_fails() -> None:
    data = {
        "expression": "v",
        "unit": "m/s",
        "units": {"v": "m/s"},
        "values": {"v": 5},
        "expected": {"value": 5, "unit": "m/s^2"},
    }

    assert _verdict(data) == "fail"
    assert "结果单位不一致" in _detail(data)


def test_an_expected_result_without_values_is_unknown_not_passed() -> None:
    data = {
        "expression": "v",
        "unit": "m/s",
        "units": {"v": "m/s"},
        "expected": {"value": 5, "unit": "m/s"},
    }

    assert _verdict(data) == "unknown"
    assert "无法回代" in _detail(data)


def test_an_expression_must_match_its_declared_unit() -> None:
    data = {
        "expression": "v",
        "unit": "m/s^2",
        "units": {"v": "m/s"},
        "values": {"v": 5},
    }

    assert _verdict(data) == "fail"
    assert "表达式量纲不一致" in _detail(data)


def test_an_expression_without_a_unit_is_unknown() -> None:
    data = {"expression": "v", "units": {"v": "m/s"}, "values": {"v": 5}}

    assert _verdict(data) == "unknown"
    assert "unit" in _detail(data)


def test_sqrt_halves_the_dimension() -> None:
    data = {
        "expression": "sqrt(area)",
        "unit": "m",
        "units": {"area": "m^2"},
        "values": {"area": 4},
    }

    assert _verdict(data) == "pass"
    assert "求值 2" in _detail(data)


def test_degree_units_are_converted_before_trigonometry() -> None:
    data = {
        "equation": "c = cos(theta)",
        "units": {"c": "", "theta": "deg"},
        "values": {"c": 0.5, "theta": 60},
    }

    assert _verdict(data) == "pass"


def test_declared_units_are_converted_to_si_before_replay() -> None:
    data = {
        "equation": "x = y",
        "units": {"x": "cm", "y": "m"},
        "values": {"x": 100, "y": 1},
    }

    assert _verdict(data) == "pass"


def test_a_numeric_tolerance_can_be_overridden() -> None:
    loose = {"equation": "1 = 1.00001", "tolerance": 0.001}
    strict = {"equation": "1 = 1.00001"}

    assert _verdict(loose) == "pass"
    assert _verdict(strict) == "fail"


def test_relative_and_absolute_tolerance_can_be_given_separately() -> None:
    data = {
        "equation": "1 = 1.00001",
        "tolerance": {"relative": 0.0, "absolute": 0.001},
    }

    assert _verdict(data) == "pass"


def test_a_negative_tolerance_is_unknown() -> None:
    data = {"equation": "1 = 1", "tolerance": -0.1}

    assert _verdict(data) == "unknown"
    assert "tolerance" in _detail(data)


def test_a_malformed_equation_is_unknown() -> None:
    for equation in ("1 = 2 = 3", "1 + = 2", "1 <= 2"):
        data = {"equation": equation}
        assert _verdict(data) == "unknown", equation


def test_non_mapping_or_non_numeric_payload_fields_are_unknown() -> None:
    assert _verdict([]) == "unknown"
    assert _verdict({"equation": 3}) == "unknown"
    assert _verdict({"equation": "1 = 1", "values": []}) == "unknown"
    assert _verdict({"equation": "1 = 1", "units": []}) == "unknown"
    assert (
        _verdict({"equation": "F = m*a", "units": {"F": "N", "m": "kg"}, "values": "x"})
        == "unknown"
    )


def test_python_syntax_is_rejected_instead_of_executed() -> None:
    for equation in (
        "__import__('os').system('echo pwned') = 0",
        "(lambda: 1)() = 1",
        "[x for x in range(3)] = 1",
    ):
        assert _verdict({"equation": equation}) == "unknown", equation


def test_unknown_function_is_unknown() -> None:
    data = {
        "expression": "foo(v)",
        "unit": "m",
        "units": {"v": "m"},
        "values": {"v": 1},
    }

    assert _verdict(data) == "unknown"
    assert "未知函数" in _detail(data)


def test_unknown_symbol_in_dimension_of_raises_value_error() -> None:
    with pytest.raises(ValueError):
        dimension_of("F + m*a", {"F": "N", "m": "kg"})


def test_an_absurd_exponent_is_rejected_without_computing_it() -> None:
    for equation in ("2**101 = 0", "9**9**9 = 0", "1e999 = 0"):
        assert _verdict({"equation": equation}) == "unknown", equation

    with pytest.raises(ValueError):
        evaluate("9**9**9", {})


def test_parse_unit_reduces_derived_units_and_prefixes() -> None:
    assert parse_unit("N").dimension == parse_unit("kg*m/s^2").dimension
    assert parse_unit("cm").scale == pytest.approx(0.01)
    assert parse_unit("Ω").dimension == parse_unit("ohm").dimension
    assert parse_unit("").dimension == parse_unit("1").dimension


def test_evaluate_never_reaches_python_builtins() -> None:
    assert evaluate("2*pi", {}) == pytest.approx(2 * 3.141592653589793)
    with pytest.raises(ValueError):
        evaluate("__import__('os')", {})


def test_render_dimension_keeps_fractional_exponents_readable() -> None:
    rendered = render_dimension(dimension_of("sqrt(area)", {"area": "m^2"}))
    assert rendered == "m"
