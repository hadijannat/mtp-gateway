"""Unit tests for JSON Schema export functionality."""

from __future__ import annotations

import json

from mtp_gateway.config.schema_export import (
    SCHEMA_VERSION,
    export_json_schema,
    export_json_schema_string,
    get_schema_version,
    validate_config_against_schema,
)


class TestExportJsonSchema:
    """Tests for JSON Schema export."""

    def test_export_returns_dict(self) -> None:
        schema = export_json_schema()
        assert isinstance(schema, dict)

    def test_export_includes_schema_keyword(self) -> None:
        schema = export_json_schema()
        assert "$schema" in schema
        assert "json-schema.org" in schema["$schema"]

    def test_export_includes_title(self) -> None:
        schema = export_json_schema()
        assert "title" in schema
        assert "MTP Gateway" in schema["title"]

    def test_export_includes_metadata(self) -> None:
        schema = export_json_schema()
        assert "x-mtp-gateway" in schema
        metadata = schema["x-mtp-gateway"]
        assert "version" in metadata
        assert "generated_at" in metadata
        assert "generator" in metadata

    def test_export_without_metadata(self) -> None:
        schema = export_json_schema(include_metadata=False)
        assert "$schema" not in schema
        assert "x-mtp-gateway" not in schema

    def test_export_with_custom_version(self) -> None:
        schema = export_json_schema(version="2.0.0")
        assert schema["x-mtp-gateway"]["version"] == "2.0.0"

    def test_export_has_properties(self) -> None:
        schema = export_json_schema()
        # Should have top-level properties for GatewayConfig
        assert "properties" in schema or "$defs" in schema

    def test_export_is_valid_json(self) -> None:
        schema = export_json_schema()
        # Should serialize to valid JSON
        json_str = json.dumps(schema)
        parsed = json.loads(json_str)
        assert parsed == schema


class TestExportJsonSchemaString:
    """Tests for JSON Schema string export."""

    def test_export_returns_string(self) -> None:
        result = export_json_schema_string()
        assert isinstance(result, str)

    def test_export_is_valid_json_string(self) -> None:
        result = export_json_schema_string()
        # Should be parseable as JSON
        schema = json.loads(result)
        assert isinstance(schema, dict)

    def test_export_with_custom_indent(self) -> None:
        result = export_json_schema_string(indent=4)
        # Should have 4-space indentation
        lines = result.split("\n")
        # Find a line with indentation
        indented_lines = [line for line in lines if line.startswith("    ")]
        assert len(indented_lines) > 0


class TestGetSchemaVersion:
    """Tests for schema version retrieval."""

    def test_returns_version_string(self) -> None:
        version = get_schema_version()
        assert isinstance(version, str)
        assert version == SCHEMA_VERSION

    def test_version_is_semver_like(self) -> None:
        version = get_schema_version()
        parts = version.split(".")
        assert len(parts) >= 2  # At least major.minor


class TestValidateConfigAgainstSchema:
    """Tests for configuration validation."""

    def test_valid_minimal_config(self) -> None:
        config = {
            "gateway": {
                "name": "TestGateway",
                "version": "1.0.0",
            },
            "opcua": {
                "endpoint": "opc.tcp://localhost:4840",
                "namespace_uri": "urn:test:gateway",
            },
            "connectors": [],
            "tags": [],
            "mtp": {
                "data_assemblies": [],
                "services": [],
            },
        }
        errors = validate_config_against_schema(config)
        assert len(errors) == 0

    def test_missing_required_field(self) -> None:
        config = {
            "gateway": {
                # Missing 'name' which is required
                "version": "1.0.0",
            },
            "opcua": {
                "endpoint": "opc.tcp://localhost:4840",
                "namespace_uri": "urn:test:gateway",
            },
        }
        errors = validate_config_against_schema(config)
        assert len(errors) > 0
        # Should mention the missing field
        error_text = " ".join(errors).lower()
        assert "name" in error_text or "required" in error_text

    def test_invalid_type(self) -> None:
        config = {
            "gateway": {
                "name": "TestGateway",
                "version": 123,  # Should be string
            },
            "opcua": {
                "endpoint": "opc.tcp://localhost:4840",
                "namespace_uri": "urn:test:gateway",
            },
        }
        errors = validate_config_against_schema(config)
        assert len(errors) > 0

    def test_valid_config_with_connectors(self) -> None:
        config = {
            "gateway": {
                "name": "TestGateway",
                "version": "1.0.0",
            },
            "opcua": {
                "endpoint": "opc.tcp://localhost:4840",
                "namespace_uri": "urn:test:gateway",
            },
            "connectors": [
                {
                    "type": "modbus_tcp",
                    "name": "plc1",
                    "host": "192.168.1.100",
                }
            ],
            "tags": [
                {
                    "name": "temp",
                    "connector": "plc1",
                    "address": "40001",
                    "datatype": "float32",
                }
            ],
            "mtp": {
                "data_assemblies": [],
                "services": [],
            },
        }
        errors = validate_config_against_schema(config)
        assert len(errors) == 0

    def test_completely_invalid_config(self) -> None:
        config = {"random": "data"}
        errors = validate_config_against_schema(config)
        assert len(errors) > 0

    def test_empty_config(self) -> None:
        config: dict[str, object] = {}
        errors = validate_config_against_schema(config)
        assert len(errors) > 0
