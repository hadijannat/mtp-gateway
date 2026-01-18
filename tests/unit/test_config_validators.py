"""Unit tests for protocol-specific address validators."""

from __future__ import annotations

import pytest

from mtp_gateway.config.validators import (
    EIPAddressValidator,
    ModbusAddressValidator,
    OPCUANodeIdValidator,
    S7AddressValidator,
    get_validator_for_protocol,
    validate_tag_address,
)


class TestModbusAddressValidator:
    """Tests for Modbus address validation."""

    @pytest.fixture
    def validator(self) -> ModbusAddressValidator:
        return ModbusAddressValidator()

    def test_valid_coil_address(self, validator: ModbusAddressValidator) -> None:
        result = validator.validate("00001")
        assert result.valid
        assert result.normalized == "1"

    def test_valid_holding_register(self, validator: ModbusAddressValidator) -> None:
        result = validator.validate("40001")
        assert result.valid
        assert result.normalized == "40001"

    def test_valid_input_register(self, validator: ModbusAddressValidator) -> None:
        result = validator.validate("30001")
        assert result.valid
        assert result.normalized == "30001"

    def test_valid_discrete_input(self, validator: ModbusAddressValidator) -> None:
        result = validator.validate("10001")
        assert result.valid
        assert result.normalized == "10001"

    def test_valid_with_unit_id(self, validator: ModbusAddressValidator) -> None:
        result = validator.validate("1:40001")
        assert result.valid
        assert result.normalized == "1:40001"

    def test_invalid_out_of_range(self, validator: ModbusAddressValidator) -> None:
        result = validator.validate("25000")
        assert not result.valid
        assert "not in a standard register range" in result.error

    def test_invalid_format(self, validator: ModbusAddressValidator) -> None:
        result = validator.validate("not_a_number")
        assert not result.valid
        assert "Invalid Modbus address format" in result.error

    def test_extended_holding_register(self, validator: ModbusAddressValidator) -> None:
        result = validator.validate("400001")
        assert result.valid


class TestS7AddressValidator:
    """Tests for S7 address validation."""

    @pytest.fixture
    def validator(self) -> S7AddressValidator:
        return S7AddressValidator()

    def test_valid_db_word(self, validator: S7AddressValidator) -> None:
        result = validator.validate("DB1.DBW0")
        assert result.valid
        assert result.normalized == "DB1.DBW0"

    def test_valid_db_dword(self, validator: S7AddressValidator) -> None:
        result = validator.validate("DB100.DBD10")
        assert result.valid
        assert result.normalized == "DB100.DBD10"

    def test_valid_db_bit(self, validator: S7AddressValidator) -> None:
        result = validator.validate("DB1.DBX0.0")
        assert result.valid
        assert result.normalized == "DB1.DBX0.0"

    def test_valid_marker_bit(self, validator: S7AddressValidator) -> None:
        result = validator.validate("M0.0")
        assert result.valid
        assert result.normalized == "M0.0"

    def test_valid_marker_word(self, validator: S7AddressValidator) -> None:
        result = validator.validate("MW10")
        assert result.valid
        assert result.normalized == "MW10"

    def test_valid_input_bit(self, validator: S7AddressValidator) -> None:
        result = validator.validate("I0.5")
        assert result.valid
        assert result.normalized == "I0.5"

    def test_valid_output_byte(self, validator: S7AddressValidator) -> None:
        result = validator.validate("QB0")
        assert result.valid
        assert result.normalized == "QB0"

    def test_valid_timer(self, validator: S7AddressValidator) -> None:
        result = validator.validate("T5")
        assert result.valid
        assert result.normalized == "T5"

    def test_valid_counter(self, validator: S7AddressValidator) -> None:
        result = validator.validate("C10")
        assert result.valid
        assert result.normalized == "C10"

    def test_invalid_format(self, validator: S7AddressValidator) -> None:
        result = validator.validate("XYZ123")
        assert not result.valid
        assert "Invalid S7 address format" in result.error

    def test_db_bit_missing_bit_number(self, validator: S7AddressValidator) -> None:
        result = validator.validate("DB1.DBX0")
        assert not result.valid
        assert "bit number" in result.error

    def test_db_bit_invalid_bit_number(self, validator: S7AddressValidator) -> None:
        result = validator.validate("DB1.DBX0.9")
        assert not result.valid
        assert "0-7" in result.error

    def test_case_insensitive(self, validator: S7AddressValidator) -> None:
        result = validator.validate("db1.dbw0")
        assert result.valid
        assert result.normalized == "DB1.DBW0"


class TestEIPAddressValidator:
    """Tests for EtherNet/IP address validation."""

    @pytest.fixture
    def validator(self) -> EIPAddressValidator:
        return EIPAddressValidator()

    def test_valid_simple_tag(self, validator: EIPAddressValidator) -> None:
        result = validator.validate("MyTag")
        assert result.valid

    def test_valid_tag_with_underscore(self, validator: EIPAddressValidator) -> None:
        result = validator.validate("My_Tag_123")
        assert result.valid

    def test_valid_array_element(self, validator: EIPAddressValidator) -> None:
        result = validator.validate("MyArray[0]")
        assert result.valid

    def test_valid_multi_dimensional_array(self, validator: EIPAddressValidator) -> None:
        result = validator.validate("Matrix[1,2]")
        assert result.valid

    def test_valid_struct_member(self, validator: EIPAddressValidator) -> None:
        result = validator.validate("MyStruct.Member")
        assert result.valid

    def test_valid_program_scoped(self, validator: EIPAddressValidator) -> None:
        result = validator.validate("Program:MainProgram.LocalTag")
        assert result.valid

    def test_valid_complex_path(self, validator: EIPAddressValidator) -> None:
        result = validator.validate("Struct.Array[0].Member")
        assert result.valid

    def test_invalid_starting_with_number(self, validator: EIPAddressValidator) -> None:
        result = validator.validate("123Tag")
        assert not result.valid

    def test_invalid_empty(self, validator: EIPAddressValidator) -> None:
        result = validator.validate("")
        assert not result.valid

    def test_invalid_special_chars(self, validator: EIPAddressValidator) -> None:
        result = validator.validate("Tag@Name")
        assert not result.valid


class TestOPCUANodeIdValidator:
    """Tests for OPC UA NodeId validation."""

    @pytest.fixture
    def validator(self) -> OPCUANodeIdValidator:
        return OPCUANodeIdValidator()

    def test_valid_numeric_nodeid(self, validator: OPCUANodeIdValidator) -> None:
        result = validator.validate("ns=2;i=1234")
        assert result.valid

    def test_valid_string_nodeid(self, validator: OPCUANodeIdValidator) -> None:
        result = validator.validate("ns=2;s=MyNode")
        assert result.valid

    def test_valid_expanded_string(self, validator: OPCUANodeIdValidator) -> None:
        result = validator.validate("nsu=urn:example:namespace;s=MyTag")
        assert result.valid

    def test_valid_expanded_numeric(self, validator: OPCUANodeIdValidator) -> None:
        result = validator.validate("nsu=http://example.com;i=1234")
        assert result.valid

    def test_valid_guid_nodeid(self, validator: OPCUANodeIdValidator) -> None:
        result = validator.validate("ns=2;g=12345678-1234-1234-1234-123456789abc")
        assert result.valid

    def test_valid_opaque_nodeid(self, validator: OPCUANodeIdValidator) -> None:
        result = validator.validate("ns=2;b=SGVsbG8=")
        assert result.valid

    def test_invalid_empty(self, validator: OPCUANodeIdValidator) -> None:
        result = validator.validate("")
        assert not result.valid

    def test_invalid_format(self, validator: OPCUANodeIdValidator) -> None:
        result = validator.validate("MyNode")
        assert not result.valid
        assert "Invalid OPC UA NodeId format" in result.error


class TestGetValidatorForProtocol:
    """Tests for protocol validator lookup."""

    def test_modbus_tcp(self) -> None:
        validator = get_validator_for_protocol("modbus_tcp")
        assert isinstance(validator, ModbusAddressValidator)

    def test_modbus_aliases(self) -> None:
        assert get_validator_for_protocol("modbus") is not None
        assert get_validator_for_protocol("modbus_rtu") is not None

    def test_s7_aliases(self) -> None:
        assert get_validator_for_protocol("s7") is not None
        assert get_validator_for_protocol("siemens") is not None

    def test_eip_aliases(self) -> None:
        assert get_validator_for_protocol("eip") is not None
        assert get_validator_for_protocol("ethernet_ip") is not None
        assert get_validator_for_protocol("cip") is not None

    def test_opcua_aliases(self) -> None:
        assert get_validator_for_protocol("opcua") is not None
        assert get_validator_for_protocol("opc_ua") is not None
        assert get_validator_for_protocol("opcua_client") is not None

    def test_unknown_protocol(self) -> None:
        validator = get_validator_for_protocol("unknown_protocol")
        assert validator is None


class TestValidateTagAddress:
    """Tests for the convenience validation function."""

    def test_validates_modbus_address(self) -> None:
        result = validate_tag_address("40001", "modbus_tcp")
        assert result.valid

    def test_unknown_protocol_allows_any(self) -> None:
        result = validate_tag_address("anything_goes", "custom_protocol")
        assert result.valid
        assert result.normalized == "anything_goes"
