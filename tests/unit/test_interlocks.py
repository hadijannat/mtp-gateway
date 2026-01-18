"""Unit tests for Interlock Evaluation (Phase 9).

Tests for:
- InterlockBinding: Configuration for binding an element to an interlock source
- InterlockResult: Result of interlock evaluation
- InterlockEvaluator: Evaluates interlock conditions based on tag values

These tests are written FIRST per TDD - they will fail until implementation.
"""

from __future__ import annotations

from typing import Any

import pytest

# These imports will fail initially - module doesn't exist yet
from mtp_gateway.domain.rules.interlocks import (
    ComparisonOperator,
    InterlockBinding,
    InterlockEvaluator,
    InterlockResult,
)

# =============================================================================
# InterlockBinding Tests
# =============================================================================


class TestInterlockBinding:
    """Tests for InterlockBinding configuration."""

    def test_creates_with_defaults(self) -> None:
        """Should create binding with default condition and ref_value."""
        binding = InterlockBinding(
            element_name="Valve1",
            source_tag="Safety.Trip",
        )

        assert binding.element_name == "Valve1"
        assert binding.source_tag == "Safety.Trip"
        assert binding.condition == ComparisonOperator.EQ
        assert binding.ref_value is True

    def test_custom_condition(self) -> None:
        """Should accept custom comparison condition."""
        binding = InterlockBinding(
            element_name="Motor1",
            source_tag="Temp.Value",
            condition=ComparisonOperator.GT,
            ref_value=100.0,
        )

        assert binding.condition == ComparisonOperator.GT
        assert binding.ref_value == 100.0

    def test_all_comparison_operators(self) -> None:
        """Should support all comparison operators."""
        operators = [
            ComparisonOperator.EQ,
            ComparisonOperator.NE,
            ComparisonOperator.GT,
            ComparisonOperator.GE,
            ComparisonOperator.LT,
            ComparisonOperator.LE,
        ]

        for op in operators:
            binding = InterlockBinding(
                element_name="Element",
                source_tag="Tag",
                condition=op,
                ref_value=0,
            )
            assert binding.condition == op


# =============================================================================
# InterlockResult Tests
# =============================================================================


class TestInterlockResult:
    """Tests for InterlockResult data class."""

    def test_not_interlocked_result(self) -> None:
        """Should create not-interlocked result."""
        result = InterlockResult(interlocked=False)

        assert result.interlocked is False
        assert result.reason is None
        assert result.source_tag is None

    def test_interlocked_result_with_details(self) -> None:
        """Should create interlocked result with reason and source."""
        result = InterlockResult(
            interlocked=True,
            reason="Safety trip active",
            source_tag="Safety.Trip",
        )

        assert result.interlocked is True
        assert result.reason == "Safety trip active"
        assert result.source_tag == "Safety.Trip"

    def test_is_frozen(self) -> None:
        """InterlockResult should be immutable (frozen dataclass)."""
        result = InterlockResult(interlocked=False)

        with pytest.raises(AttributeError):
            result.interlocked = True  # type: ignore[misc]


# =============================================================================
# InterlockEvaluator Tests
# =============================================================================


class TestInterlockEvaluator:
    """Tests for InterlockEvaluator."""

    def test_creates_empty(self) -> None:
        """Should create evaluator with no bindings."""
        evaluator = InterlockEvaluator(bindings={})

        assert len(evaluator.bindings) == 0

    def test_creates_with_bindings(self) -> None:
        """Should create evaluator with bindings dict."""
        bindings = {
            "Valve1": InterlockBinding(
                element_name="Valve1",
                source_tag="Safety.Trip",
            ),
        }

        evaluator = InterlockEvaluator(bindings=bindings)

        assert "Valve1" in evaluator.bindings

    def test_check_interlock_element_not_bound(self) -> None:
        """Should return not interlocked for element with no binding."""
        evaluator = InterlockEvaluator(bindings={})
        tag_values: dict[str, Any] = {"Safety.Trip": True}

        result = evaluator.check_interlock("UnboundElement", tag_values)

        assert result.interlocked is False

    def test_check_interlock_condition_true(self) -> None:
        """Should return interlocked when condition evaluates to True."""
        bindings = {
            "Valve1": InterlockBinding(
                element_name="Valve1",
                source_tag="Safety.Trip",
                condition=ComparisonOperator.EQ,
                ref_value=True,
            ),
        }
        evaluator = InterlockEvaluator(bindings=bindings)
        tag_values = {"Safety.Trip": True}  # Matches condition

        result = evaluator.check_interlock("Valve1", tag_values)

        assert result.interlocked is True
        assert result.source_tag == "Safety.Trip"

    def test_check_interlock_condition_false(self) -> None:
        """Should return not interlocked when condition evaluates to False."""
        bindings = {
            "Valve1": InterlockBinding(
                element_name="Valve1",
                source_tag="Safety.Trip",
                condition=ComparisonOperator.EQ,
                ref_value=True,
            ),
        }
        evaluator = InterlockEvaluator(bindings=bindings)
        tag_values = {"Safety.Trip": False}  # Does NOT match condition

        result = evaluator.check_interlock("Valve1", tag_values)

        assert result.interlocked is False

    def test_check_interlock_missing_tag_value(self) -> None:
        """Should return not interlocked when source tag not in tag_values."""
        bindings = {
            "Valve1": InterlockBinding(
                element_name="Valve1",
                source_tag="Safety.Trip",
            ),
        }
        evaluator = InterlockEvaluator(bindings=bindings)
        tag_values: dict[str, Any] = {}  # Missing Safety.Trip

        result = evaluator.check_interlock("Valve1", tag_values)

        assert result.interlocked is False

    def test_check_interlock_with_eq_operator(self) -> None:
        """EQ operator should trigger interlock when value equals ref."""
        bindings = {
            "Motor1": InterlockBinding(
                element_name="Motor1",
                source_tag="State.Value",
                condition=ComparisonOperator.EQ,
                ref_value=5,
            ),
        }
        evaluator = InterlockEvaluator(bindings=bindings)

        # Should be interlocked when value == 5
        assert evaluator.check_interlock("Motor1", {"State.Value": 5}).interlocked is True

        # Should NOT be interlocked when value != 5
        assert evaluator.check_interlock("Motor1", {"State.Value": 4}).interlocked is False

    def test_check_interlock_with_ne_operator(self) -> None:
        """NE operator should trigger interlock when value not equals ref."""
        bindings = {
            "Motor1": InterlockBinding(
                element_name="Motor1",
                source_tag="Status",
                condition=ComparisonOperator.NE,
                ref_value="OK",
            ),
        }
        evaluator = InterlockEvaluator(bindings=bindings)

        # Should be interlocked when value != "OK"
        assert evaluator.check_interlock("Motor1", {"Status": "FAULT"}).interlocked is True

        # Should NOT be interlocked when value == "OK"
        assert evaluator.check_interlock("Motor1", {"Status": "OK"}).interlocked is False

    def test_check_interlock_with_gt_operator(self) -> None:
        """GT operator should trigger interlock when value > ref."""
        bindings = {
            "Pump1": InterlockBinding(
                element_name="Pump1",
                source_tag="Temp.Value",
                condition=ComparisonOperator.GT,
                ref_value=100.0,
            ),
        }
        evaluator = InterlockEvaluator(bindings=bindings)

        # Should be interlocked when value > 100
        assert evaluator.check_interlock("Pump1", {"Temp.Value": 105.0}).interlocked is True

        # Should NOT be interlocked when value <= 100
        assert evaluator.check_interlock("Pump1", {"Temp.Value": 100.0}).interlocked is False
        assert evaluator.check_interlock("Pump1", {"Temp.Value": 95.0}).interlocked is False

    def test_check_interlock_with_ge_operator(self) -> None:
        """GE operator should trigger interlock when value >= ref."""
        bindings = {
            "Pump1": InterlockBinding(
                element_name="Pump1",
                source_tag="Pressure",
                condition=ComparisonOperator.GE,
                ref_value=50.0,
            ),
        }
        evaluator = InterlockEvaluator(bindings=bindings)

        # Should be interlocked when value >= 50
        assert evaluator.check_interlock("Pump1", {"Pressure": 50.0}).interlocked is True
        assert evaluator.check_interlock("Pump1", {"Pressure": 60.0}).interlocked is True

        # Should NOT be interlocked when value < 50
        assert evaluator.check_interlock("Pump1", {"Pressure": 49.9}).interlocked is False

    def test_check_interlock_with_lt_operator(self) -> None:
        """LT operator should trigger interlock when value < ref."""
        bindings = {
            "Heater1": InterlockBinding(
                element_name="Heater1",
                source_tag="Level",
                condition=ComparisonOperator.LT,
                ref_value=10.0,
            ),
        }
        evaluator = InterlockEvaluator(bindings=bindings)

        # Should be interlocked when value < 10
        assert evaluator.check_interlock("Heater1", {"Level": 5.0}).interlocked is True

        # Should NOT be interlocked when value >= 10
        assert evaluator.check_interlock("Heater1", {"Level": 10.0}).interlocked is False

    def test_check_interlock_with_le_operator(self) -> None:
        """LE operator should trigger interlock when value <= ref."""
        bindings = {
            "Heater1": InterlockBinding(
                element_name="Heater1",
                source_tag="Level",
                condition=ComparisonOperator.LE,
                ref_value=10.0,
            ),
        }
        evaluator = InterlockEvaluator(bindings=bindings)

        # Should be interlocked when value <= 10
        assert evaluator.check_interlock("Heater1", {"Level": 10.0}).interlocked is True
        assert evaluator.check_interlock("Heater1", {"Level": 5.0}).interlocked is True

        # Should NOT be interlocked when value > 10
        assert evaluator.check_interlock("Heater1", {"Level": 10.1}).interlocked is False

    def test_get_interlocked_elements_empty(self) -> None:
        """Should return empty set when no elements are interlocked."""
        bindings = {
            "Valve1": InterlockBinding(
                element_name="Valve1",
                source_tag="Safety.Trip",
                condition=ComparisonOperator.EQ,
                ref_value=True,
            ),
        }
        evaluator = InterlockEvaluator(bindings=bindings)
        tag_values = {"Safety.Trip": False}  # Not tripped

        interlocked = evaluator.get_interlocked_elements(tag_values)

        assert interlocked == set()

    def test_get_interlocked_elements_some_interlocked(self) -> None:
        """Should return set of element names that are interlocked."""
        bindings = {
            "Valve1": InterlockBinding(
                element_name="Valve1",
                source_tag="Zone1.Trip",
                condition=ComparisonOperator.EQ,
                ref_value=True,
            ),
            "Valve2": InterlockBinding(
                element_name="Valve2",
                source_tag="Zone2.Trip",
                condition=ComparisonOperator.EQ,
                ref_value=True,
            ),
            "Motor1": InterlockBinding(
                element_name="Motor1",
                source_tag="Zone1.Trip",  # Same source as Valve1
                condition=ComparisonOperator.EQ,
                ref_value=True,
            ),
        }
        evaluator = InterlockEvaluator(bindings=bindings)
        tag_values = {
            "Zone1.Trip": True,  # Tripped - affects Valve1 and Motor1
            "Zone2.Trip": False,  # Not tripped - Valve2 OK
        }

        interlocked = evaluator.get_interlocked_elements(tag_values)

        assert interlocked == {"Valve1", "Motor1"}
        assert "Valve2" not in interlocked

    def test_get_interlocked_elements_all_interlocked(self) -> None:
        """Should return all elements when all are interlocked."""
        bindings = {
            "Valve1": InterlockBinding(
                element_name="Valve1",
                source_tag="Master.Trip",
                condition=ComparisonOperator.EQ,
                ref_value=True,
            ),
            "Valve2": InterlockBinding(
                element_name="Valve2",
                source_tag="Master.Trip",
                condition=ComparisonOperator.EQ,
                ref_value=True,
            ),
        }
        evaluator = InterlockEvaluator(bindings=bindings)
        tag_values = {"Master.Trip": True}

        interlocked = evaluator.get_interlocked_elements(tag_values)

        assert interlocked == {"Valve1", "Valve2"}

    def test_check_service_interlocks_no_bindings(self) -> None:
        """Should return not interlocked when no bindings for service."""
        evaluator = InterlockEvaluator(bindings={})

        result = evaluator.check_service_interlocks("Reactor", tag_values={})

        assert result.interlocked is False

    def test_check_service_interlocks_interlocked(self) -> None:
        """Should return interlocked when service has interlocked elements."""
        # Service bindings are keyed by service name
        bindings = {
            "Reactor:Valve1": InterlockBinding(
                element_name="Reactor:Valve1",
                source_tag="Safety.Trip",
                condition=ComparisonOperator.EQ,
                ref_value=True,
            ),
        }
        evaluator = InterlockEvaluator(bindings=bindings)
        tag_values = {"Safety.Trip": True}

        result = evaluator.check_service_interlocks("Reactor", tag_values)

        assert result.interlocked is True

    def test_interlock_reason_includes_details(self) -> None:
        """Interlock reason should include useful diagnostic info."""
        bindings = {
            "Valve1": InterlockBinding(
                element_name="Valve1",
                source_tag="Safety.Trip",
                condition=ComparisonOperator.EQ,
                ref_value=True,
            ),
        }
        evaluator = InterlockEvaluator(bindings=bindings)
        tag_values = {"Safety.Trip": True}

        result = evaluator.check_interlock("Valve1", tag_values)

        assert result.reason is not None
        # Reason should mention the source tag
        assert "Safety.Trip" in result.reason


# =============================================================================
# Edge Cases and Error Handling
# =============================================================================


class TestInterlockEdgeCases:
    """Tests for edge cases and error handling."""

    def test_none_tag_value_treated_as_missing(self) -> None:
        """None tag value should be treated as missing (not interlocked)."""
        bindings = {
            "Valve1": InterlockBinding(
                element_name="Valve1",
                source_tag="Safety.Trip",
                condition=ComparisonOperator.EQ,
                ref_value=True,
            ),
        }
        evaluator = InterlockEvaluator(bindings=bindings)
        tag_values = {"Safety.Trip": None}

        result = evaluator.check_interlock("Valve1", tag_values)

        # None should not match True, so not interlocked
        assert result.interlocked is False

    def test_type_mismatch_in_comparison(self) -> None:
        """Should handle type mismatches gracefully (not interlocked)."""
        bindings = {
            "Valve1": InterlockBinding(
                element_name="Valve1",
                source_tag="Value",
                condition=ComparisonOperator.GT,
                ref_value=100.0,  # numeric
            ),
        }
        evaluator = InterlockEvaluator(bindings=bindings)
        tag_values = {"Value": "not_a_number"}  # string

        # Should not raise, should return not interlocked
        result = evaluator.check_interlock("Valve1", tag_values)

        assert result.interlocked is False
