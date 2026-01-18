"""Unit tests for service domain models.

Tests factory from_config() conversions, completion condition evaluation,
and state hooks retrieval for each state.
"""

from __future__ import annotations

import pytest

from mtp_gateway.config.schema import (
    ComparisonOp,
    CompletionConfig,
    ConditionConfig,
    PackMLStateName,
    ProcedureConfig,
    ProxyMode,
    ServiceConfig,
    ServiceParameterConfig,
    StateHooksConfig,
    StateTimeoutsConfig,
    TimeoutAction,
    WriteAction,
)
from mtp_gateway.domain.model.services import (
    ActingStateCondition,
    CompletionCondition,
    CompletionSpec,
    ProcedureDefinition,
    ProcedureParameter,
    ServiceDefinition,
    ServiceRuntimeState,
    StateHooks,
    StateTimeoutSpec,
)
from mtp_gateway.domain.model.tags import Quality
from mtp_gateway.domain.state_machine.packml import PackMLState, PackMLStateMachine


class TestProcedureParameter:
    """Tests for ProcedureParameter dataclass."""

    def test_creation(self) -> None:
        """ProcedureParameter should be created with all fields."""
        param = ProcedureParameter(
            name="Temperature",
            data_assembly="TempParam",
            required=True,
        )
        assert param.name == "Temperature"
        assert param.data_assembly == "TempParam"
        assert param.required is True

    def test_immutable(self) -> None:
        """ProcedureParameter should be immutable (frozen)."""
        param = ProcedureParameter(name="Test", data_assembly="DA1", required=False)
        with pytest.raises(AttributeError):
            param.name = "Changed"  # type: ignore[misc]


class TestProcedureDefinition:
    """Tests for ProcedureDefinition dataclass."""

    def test_creation(self) -> None:
        """ProcedureDefinition should be created with all fields."""
        proc = ProcedureDefinition(
            id=1,
            name="Heating",
            is_default=True,
            parameters=(
                ProcedureParameter(name="Target", data_assembly="TargetTemp", required=True),
            ),
        )
        assert proc.id == 1
        assert proc.name == "Heating"
        assert proc.is_default is True
        assert len(proc.parameters) == 1

    def test_from_config(self) -> None:
        """ProcedureDefinition.from_config() should convert config correctly."""
        config = ProcedureConfig(
            id=2,
            name="Cooling",
            is_default=False,
            parameters=[
                ServiceParameterConfig(name="SetPoint", data_assembly="CoolSP", required=True),
                ServiceParameterConfig(name="Rate", data_assembly="CoolRate", required=False),
            ],
        )
        proc = ProcedureDefinition.from_config(config)

        assert proc.id == 2
        assert proc.name == "Cooling"
        assert proc.is_default is False
        assert len(proc.parameters) == 2
        assert proc.parameters[0].name == "SetPoint"
        assert proc.parameters[1].required is False

    def test_immutable(self) -> None:
        """ProcedureDefinition should be immutable (frozen)."""
        proc = ProcedureDefinition(id=1, name="Test", is_default=False, parameters=())
        with pytest.raises(AttributeError):
            proc.name = "Changed"  # type: ignore[misc]


class TestCompletionCondition:
    """Tests for CompletionCondition dataclass."""

    def test_creation(self) -> None:
        """CompletionCondition should be created with all fields."""
        cond = CompletionCondition(
            tag="ProcessComplete",
            operator=ComparisonOp.EQ,
            reference=True,
        )
        assert cond.tag == "ProcessComplete"
        assert cond.operator == ComparisonOp.EQ
        assert cond.reference is True

    def test_evaluate_eq_true(self) -> None:
        """EQ comparison should return True when values match."""
        cond = CompletionCondition(tag="Done", operator=ComparisonOp.EQ, reference=1)
        assert cond.evaluate(1) is True

    def test_evaluate_eq_false(self) -> None:
        """EQ comparison should return False when values differ."""
        cond = CompletionCondition(tag="Done", operator=ComparisonOp.EQ, reference=1)
        assert cond.evaluate(2) is False

    def test_evaluate_ne_true(self) -> None:
        """NE comparison should return True when values differ."""
        cond = CompletionCondition(tag="Error", operator=ComparisonOp.NE, reference=0)
        assert cond.evaluate(1) is True

    def test_evaluate_ne_false(self) -> None:
        """NE comparison should return False when values match."""
        cond = CompletionCondition(tag="Error", operator=ComparisonOp.NE, reference=0)
        assert cond.evaluate(0) is False

    def test_evaluate_gt_true(self) -> None:
        """GT comparison should return True when current > reference."""
        cond = CompletionCondition(tag="Temp", operator=ComparisonOp.GT, reference=50.0)
        assert cond.evaluate(60.0) is True

    def test_evaluate_gt_false(self) -> None:
        """GT comparison should return False when current <= reference."""
        cond = CompletionCondition(tag="Temp", operator=ComparisonOp.GT, reference=50.0)
        assert cond.evaluate(50.0) is False

    def test_evaluate_ge_true(self) -> None:
        """GE comparison should return True when current >= reference."""
        cond = CompletionCondition(tag="Level", operator=ComparisonOp.GE, reference=100)
        assert cond.evaluate(100) is True
        assert cond.evaluate(150) is True

    def test_evaluate_ge_false(self) -> None:
        """GE comparison should return False when current < reference."""
        cond = CompletionCondition(tag="Level", operator=ComparisonOp.GE, reference=100)
        assert cond.evaluate(99) is False

    def test_evaluate_lt_true(self) -> None:
        """LT comparison should return True when current < reference."""
        cond = CompletionCondition(tag="Pressure", operator=ComparisonOp.LT, reference=10.0)
        assert cond.evaluate(5.0) is True

    def test_evaluate_lt_false(self) -> None:
        """LT comparison should return False when current >= reference."""
        cond = CompletionCondition(tag="Pressure", operator=ComparisonOp.LT, reference=10.0)
        assert cond.evaluate(10.0) is False

    def test_evaluate_le_true(self) -> None:
        """LE comparison should return True when current <= reference."""
        cond = CompletionCondition(tag="Flow", operator=ComparisonOp.LE, reference=5.0)
        assert cond.evaluate(5.0) is True
        assert cond.evaluate(3.0) is True

    def test_evaluate_le_false(self) -> None:
        """LE comparison should return False when current > reference."""
        cond = CompletionCondition(tag="Flow", operator=ComparisonOp.LE, reference=5.0)
        assert cond.evaluate(6.0) is False

    def test_evaluate_bool(self) -> None:
        """Evaluation should work with boolean values."""
        cond = CompletionCondition(tag="Ready", operator=ComparisonOp.EQ, reference=True)
        assert cond.evaluate(True) is True
        assert cond.evaluate(False) is False

    def test_evaluate_string(self) -> None:
        """Evaluation should work with string values."""
        cond = CompletionCondition(tag="Status", operator=ComparisonOp.EQ, reference="DONE")
        assert cond.evaluate("DONE") is True
        assert cond.evaluate("RUNNING") is False


class TestStateHooks:
    """Tests for StateHooks dataclass."""

    def test_creation(self) -> None:
        """StateHooks should be created with tuple fields."""
        hooks = StateHooks(
            on_starting=(WriteAction(tag="Start", value=True),),
            on_execute=(WriteAction(tag="Run", value=True),),
            on_completing=(),
            on_completed=(),
            on_stopping=(WriteAction(tag="Stop", value=True),),
            on_stopped=(),
            on_aborting=(WriteAction(tag="Abort", value=True),),
            on_aborted=(),
            on_holding=(),
            on_held=(),
            on_unholding=(),
            on_resetting=(),
        )
        assert len(hooks.on_starting) == 1
        assert hooks.on_starting[0].tag == "Start"


def test_service_definition_includes_timeouts_and_conditions() -> None:
    """ServiceDefinition should include timeouts and acting conditions."""
    config = ServiceConfig(
        name="ServiceWithTimeouts",
        mode=ProxyMode.THICK,
        state_hooks=StateHooksConfig(),
        timeouts=StateTimeoutsConfig(
            auto_complete_acting_states=False,
            timeouts={PackMLStateName.STARTING: 5.0},
        ),
        acting_state_conditions={
            PackMLStateName.STARTING: ConditionConfig(
                tag="ready",
                op=ComparisonOp.EQ,
                ref=True,
            )
        },
    )

    definition = ServiceDefinition.from_config(config)
    assert isinstance(definition.timeouts, StateTimeoutSpec)
    assert definition.timeouts.auto_complete_acting_states is False
    assert definition.timeouts.timeouts[PackMLState.STARTING] == 5.0
    assert any(
        isinstance(cond, ActingStateCondition) and cond.state == PackMLState.STARTING
        for cond in definition.acting_state_conditions
    )

    def test_get_hooks_for_starting(self) -> None:
        """get_hooks_for_state(STARTING) should return on_starting hooks."""
        hooks = StateHooks(
            on_starting=(WriteAction(tag="Start", value=True),),
            on_execute=(),
            on_completing=(),
            on_completed=(),
            on_stopping=(),
            on_stopped=(),
            on_aborting=(),
            on_aborted=(),
            on_holding=(),
            on_held=(),
            on_unholding=(),
            on_resetting=(),
        )
        result = hooks.get_hooks_for_state(PackMLState.STARTING)
        assert len(result) == 1
        assert result[0].tag == "Start"

    def test_get_hooks_for_execute(self) -> None:
        """get_hooks_for_state(EXECUTE) should return on_execute hooks."""
        hooks = StateHooks(
            on_starting=(),
            on_execute=(WriteAction(tag="Run", value=True),),
            on_completing=(),
            on_completed=(),
            on_stopping=(),
            on_stopped=(),
            on_aborting=(),
            on_aborted=(),
            on_holding=(),
            on_held=(),
            on_unholding=(),
            on_resetting=(),
        )
        result = hooks.get_hooks_for_state(PackMLState.EXECUTE)
        assert len(result) == 1
        assert result[0].tag == "Run"

    def test_get_hooks_for_unknown_state_returns_empty(self) -> None:
        """get_hooks_for_state() should return empty tuple for unmapped states."""
        hooks = StateHooks(
            on_starting=(),
            on_execute=(),
            on_completing=(),
            on_completed=(),
            on_stopping=(),
            on_stopped=(),
            on_aborting=(),
            on_aborted=(),
            on_holding=(),
            on_held=(),
            on_unholding=(),
            on_resetting=(),
        )
        # IDLE has no hooks
        result = hooks.get_hooks_for_state(PackMLState.IDLE)
        assert result == ()

    def test_from_config(self) -> None:
        """StateHooks.from_config() should convert config correctly."""
        config = StateHooksConfig(
            on_starting=[WriteAction(tag="PLC.Start", value=True)],
            on_execute=[WriteAction(tag="PLC.Run", value=True)],
            on_stopping=[WriteAction(tag="PLC.Stop", value=True)],
        )
        hooks = StateHooks.from_config(config)

        assert len(hooks.on_starting) == 1
        assert hooks.on_starting[0].tag == "PLC.Start"
        assert len(hooks.on_execute) == 1
        assert len(hooks.on_stopping) == 1


class TestCompletionSpec:
    """Tests for CompletionSpec dataclass."""

    def test_creation_self_completing(self) -> None:
        """CompletionSpec with self_completing flag."""
        spec = CompletionSpec(
            self_completing=True,
            condition=None,
            timeout_s=None,
        )
        assert spec.self_completing is True
        assert spec.condition is None

    def test_creation_with_condition(self) -> None:
        """CompletionSpec with completion condition."""
        cond = CompletionCondition(tag="Done", operator=ComparisonOp.EQ, reference=True)
        spec = CompletionSpec(
            self_completing=False,
            condition=cond,
            timeout_s=60.0,
        )
        assert spec.condition is not None
        assert spec.timeout_s == 60.0

    def test_from_config_self_completing(self) -> None:
        """CompletionSpec.from_config() with self_completing."""
        config = CompletionConfig(self_completing=True)
        spec = CompletionSpec.from_config(config)

        assert spec.self_completing is True
        assert spec.condition is None

    def test_from_config_with_condition(self) -> None:
        """CompletionSpec.from_config() with condition."""
        config = CompletionConfig(
            self_completing=False,
            condition=ConditionConfig(tag="PLC.Done", op=ComparisonOp.EQ, ref=True),
            timeout_s=30.0,
        )
        spec = CompletionSpec.from_config(config)

        assert spec.self_completing is False
        assert spec.condition is not None
        assert spec.condition.tag == "PLC.Done"
        assert spec.timeout_s == 30.0


class TestServiceDefinition:
    """Tests for ServiceDefinition dataclass."""

    def test_creation(self) -> None:
        """ServiceDefinition should be created with all fields."""
        service = ServiceDefinition(
            name="HeatingService",
            mode=ProxyMode.THICK,
            procedures=(ProcedureDefinition(id=0, name="Default", is_default=True, parameters=()),),
            parameters=(),
            state_hooks=StateHooks(
                on_starting=(),
                on_execute=(),
                on_completing=(),
                on_completed=(),
                on_stopping=(),
                on_stopped=(),
                on_aborting=(),
                on_aborted=(),
                on_holding=(),
                on_held=(),
                on_unholding=(),
                on_resetting=(),
            ),
            completion=CompletionSpec(self_completing=True, condition=None, timeout_s=None),
            timeouts=StateTimeoutSpec(
                auto_complete_acting_states=True,
                timeouts={},
                on_timeout=TimeoutAction.ABORT,
            ),
            acting_state_conditions=(),
            state_cur_tag=None,
            command_op_tag=None,
        )
        assert service.name == "HeatingService"
        assert service.mode == ProxyMode.THICK

    def test_from_config_thick_proxy(self) -> None:
        """ServiceDefinition.from_config() for thick proxy mode."""
        config = ServiceConfig(
            name="ThickService",
            mode=ProxyMode.THICK,
            procedures=[
                ProcedureConfig(id=0, name="Main", is_default=True),
                ProcedureConfig(id=1, name="Alt", is_default=False),
            ],
            state_hooks=StateHooksConfig(
                on_starting=[WriteAction(tag="PLC.Start", value=True)],
            ),
            completion=CompletionConfig(self_completing=True),
        )
        service = ServiceDefinition.from_config(config)

        assert service.name == "ThickService"
        assert service.mode == ProxyMode.THICK
        assert len(service.procedures) == 2
        assert service.completion.self_completing is True

    def test_from_config_thin_proxy(self) -> None:
        """ServiceDefinition.from_config() for thin proxy mode."""
        config = ServiceConfig(
            name="ThinService",
            mode=ProxyMode.THIN,
            state_cur_tag="PLC.StateCur",
            command_op_tag="PLC.CommandOp",
        )
        service = ServiceDefinition.from_config(config)

        assert service.name == "ThinService"
        assert service.mode == ProxyMode.THIN
        assert service.state_cur_tag == "PLC.StateCur"
        assert service.command_op_tag == "PLC.CommandOp"

    def test_immutable(self) -> None:
        """ServiceDefinition should be immutable (frozen)."""
        service = ServiceDefinition(
            name="Test",
            mode=ProxyMode.THICK,
            procedures=(),
            parameters=(),
            state_hooks=StateHooks(
                on_starting=(),
                on_execute=(),
                on_completing=(),
                on_completed=(),
                on_stopping=(),
                on_stopped=(),
                on_aborting=(),
                on_aborted=(),
                on_holding=(),
                on_held=(),
                on_unholding=(),
                on_resetting=(),
            ),
            completion=CompletionSpec(self_completing=True, condition=None, timeout_s=None),
            timeouts=StateTimeoutSpec(
                auto_complete_acting_states=True,
                timeouts={},
                on_timeout=TimeoutAction.ABORT,
            ),
            acting_state_conditions=(),
            state_cur_tag=None,
            command_op_tag=None,
        )
        with pytest.raises(AttributeError):
            service.name = "Changed"  # type: ignore[misc]


class TestServiceRuntimeState:
    """Tests for ServiceRuntimeState dataclass."""

    @pytest.fixture
    def service_def(self) -> ServiceDefinition:
        """Create a basic service definition for tests."""
        return ServiceDefinition(
            name="TestService",
            mode=ProxyMode.THICK,
            procedures=(ProcedureDefinition(id=0, name="Main", is_default=True, parameters=()),),
            parameters=(),
            state_hooks=StateHooks(
                on_starting=(),
                on_execute=(),
                on_completing=(),
                on_completed=(),
                on_stopping=(),
                on_stopped=(),
                on_aborting=(),
                on_aborted=(),
                on_holding=(),
                on_held=(),
                on_unholding=(),
                on_resetting=(),
            ),
            completion=CompletionSpec(self_completing=True, condition=None, timeout_s=None),
            timeouts=StateTimeoutSpec(
                auto_complete_acting_states=True,
                timeouts={},
                on_timeout=TimeoutAction.ABORT,
            ),
            acting_state_conditions=(),
            state_cur_tag=None,
            command_op_tag=None,
        )

    def test_creation(self, service_def: ServiceDefinition) -> None:
        """ServiceRuntimeState should be created with required fields."""
        sm = PackMLStateMachine("TestService")
        runtime = ServiceRuntimeState(
            definition=service_def,
            state_machine=sm,
            current_procedure_id=None,
            execute_start_time=None,
            quality=Quality.GOOD,
        )

        assert runtime.definition.name == "TestService"
        assert runtime.state_machine is sm
        assert runtime.current_procedure_id is None
        assert runtime.quality == Quality.GOOD

    def test_mutable(self, service_def: ServiceDefinition) -> None:
        """ServiceRuntimeState should be mutable (slots but not frozen)."""
        sm = PackMLStateMachine("TestService")
        runtime = ServiceRuntimeState(
            definition=service_def,
            state_machine=sm,
            current_procedure_id=None,
            execute_start_time=None,
            quality=Quality.GOOD,
        )

        # Should be mutable
        runtime.current_procedure_id = 1
        assert runtime.current_procedure_id == 1

        runtime.quality = Quality.BAD
        assert runtime.quality == Quality.BAD

    def test_tracks_procedure_id(self, service_def: ServiceDefinition) -> None:
        """ServiceRuntimeState should track current procedure ID."""
        sm = PackMLStateMachine("TestService")
        runtime = ServiceRuntimeState(
            definition=service_def,
            state_machine=sm,
            current_procedure_id=0,
            execute_start_time=None,
            quality=Quality.GOOD,
        )

        assert runtime.current_procedure_id == 0
        runtime.current_procedure_id = 1
        assert runtime.current_procedure_id == 1
