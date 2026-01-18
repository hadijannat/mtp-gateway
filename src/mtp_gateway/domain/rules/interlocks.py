"""Interlock evaluation rules for MTP Gateway.

Provides interlock enforcement for active elements and services:
- InterlockBinding: Defines how an element is bound to an interlock source
- InterlockResult: Result of interlock evaluation
- InterlockEvaluator: Evaluates conditions and determines interlock state

Interlock philosophy:
- Interlocks BLOCK dangerous operations (START, RESUME, UNHOLD)
- Interlocks do NOT block safety operations (ABORT, STOP)
- Interlock state is determined by tag values at evaluation time
- Missing or invalid tag values result in NOT interlocked (fail-open)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ComparisonOperator(str, Enum):
    """Comparison operators for interlock conditions."""

    EQ = "eq"  # Equal
    NE = "ne"  # Not equal
    GT = "gt"  # Greater than
    GE = "ge"  # Greater than or equal
    LT = "lt"  # Less than
    LE = "le"  # Less than or equal


@dataclass
class InterlockBinding:
    """Configuration for binding an element to an interlock source.

    Defines the relationship between an active element (valve, drive, etc.)
    and a tag that determines its interlock state.

    When the source tag value matches the condition (e.g., value == ref_value
    for EQ operator), the element is considered interlocked and cannot
    execute START/RESUME/UNHOLD commands.

    Attributes:
        element_name: Name of the element being interlocked
        source_tag: Tag that provides the interlock signal
        condition: Comparison operator for evaluation
        ref_value: Reference value for comparison
    """

    element_name: str
    source_tag: str
    condition: ComparisonOperator = ComparisonOperator.EQ
    ref_value: Any = True


@dataclass(frozen=True)
class InterlockResult:
    """Result of interlock evaluation.

    Immutable data class containing the result of checking whether
    an element is interlocked, along with diagnostic information.

    Attributes:
        interlocked: Whether the element is currently interlocked
        reason: Human-readable explanation if interlocked
        source_tag: The tag that caused the interlock
    """

    interlocked: bool
    reason: str | None = None
    source_tag: str | None = None


@dataclass
class InterlockEvaluator:
    """Evaluates interlock conditions for active elements.

    Holds bindings between elements and their interlock sources,
    and provides methods to check interlock state based on current
    tag values.

    Usage:
        bindings = {"Valve1": InterlockBinding(...)}
        evaluator = InterlockEvaluator(bindings)
        result = evaluator.check_interlock("Valve1", {"Tag1": value})
        if result.interlocked:
            # Block operation

    Attributes:
        bindings: Dict mapping element names to their interlock bindings
    """

    bindings: dict[str, InterlockBinding]

    def check_interlock(self, element_name: str, tag_values: dict[str, Any]) -> InterlockResult:
        """Check if element is interlocked based on bound tag values.

        Evaluates the interlock condition for the named element against
        the provided tag values.

        Args:
            element_name: Name of the element to check
            tag_values: Current tag values (tag_name -> value)

        Returns:
            InterlockResult indicating interlock state and reason
        """
        binding = self.bindings.get(element_name)
        if binding is None:
            return InterlockResult(interlocked=False)

        tag_value = tag_values.get(binding.source_tag)

        # Missing or None tag value -> not interlocked (fail-open)
        if tag_value is None:
            return InterlockResult(interlocked=False)

        try:
            is_interlocked = self._evaluate_condition(
                tag_value, binding.condition, binding.ref_value
            )
        except (TypeError, ValueError):
            # Type mismatch or comparison error -> not interlocked
            return InterlockResult(interlocked=False)

        if is_interlocked:
            return InterlockResult(
                interlocked=True,
                reason=(
                    "Interlock active: "
                    f"{binding.source_tag} {binding.condition.value} {binding.ref_value}"
                ),
                source_tag=binding.source_tag,
            )

        return InterlockResult(interlocked=False)

    def _evaluate_condition(self, value: Any, op: ComparisonOperator, ref: Any) -> bool:
        """Evaluate a comparison condition.

        Args:
            value: Current tag value
            op: Comparison operator
            ref: Reference value

        Returns:
            True if condition is met (element should be interlocked)
        """
        match op:
            case ComparisonOperator.EQ:
                return bool(value == ref)
            case ComparisonOperator.NE:
                return bool(value != ref)
            case ComparisonOperator.GT:
                return bool(value > ref)
            case ComparisonOperator.GE:
                return bool(value >= ref)
            case ComparisonOperator.LT:
                return bool(value < ref)
            case ComparisonOperator.LE:
                return bool(value <= ref)

    def get_interlocked_elements(self, tag_values: dict[str, Any]) -> set[str]:
        """Return all currently interlocked element names.

        Evaluates all bindings against the provided tag values and
        returns the set of element names that are interlocked.

        Args:
            tag_values: Current tag values (tag_name -> value)

        Returns:
            Set of element names that are currently interlocked
        """
        interlocked: set[str] = set()

        for element_name in self.bindings:
            result = self.check_interlock(element_name, tag_values)
            if result.interlocked:
                interlocked.add(element_name)

        return interlocked

    def check_service_interlocks(
        self, service_name: str, tag_values: dict[str, Any]
    ) -> InterlockResult:
        """Check if a service has any interlocked elements.

        Service bindings use the convention "ServiceName:ElementName"
        as the element name in the bindings dict.

        Args:
            service_name: Name of the service to check
            tag_values: Current tag values

        Returns:
            InterlockResult indicating if service is interlocked
        """
        prefix = f"{service_name}:"

        for element_name in self.bindings:
            if element_name.startswith(prefix):
                result = self.check_interlock(element_name, tag_values)
                if result.interlocked:
                    return result

        return InterlockResult(interlocked=False)
