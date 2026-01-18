"""JSON Schema export for GatewayConfig.

Exports the configuration schema for external validation,
documentation, and tooling integration.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from mtp_gateway.config.schema import GatewayConfig

# Schema version tracks breaking changes to config format
SCHEMA_VERSION = "1.0.0"


def export_json_schema(
    *,
    version: str | None = None,
    include_metadata: bool = True,
) -> dict[str, Any]:
    """Export GatewayConfig as JSON Schema with optional metadata.

    Args:
        version: Schema version to embed. Defaults to SCHEMA_VERSION.
        include_metadata: Whether to include $schema, title, and metadata.

    Returns:
        JSON Schema dictionary compatible with JSON Schema Draft 2020-12.
    """
    # Generate schema from Pydantic model
    schema = GatewayConfig.model_json_schema(mode="serialization")

    if include_metadata:
        # Add metadata fields
        schema_version = version or SCHEMA_VERSION
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = f"https://mtp-gateway.example.com/schemas/config/v{schema_version}"
        schema["title"] = "MTP Gateway Configuration Schema"
        schema["description"] = (
            "Configuration schema for MTP Gateway - a production-grade gateway "
            "bridging legacy PLCs to MTP-compliant OPC UA interfaces following VDI/VDE/NAMUR 2658."
        )

        # Add custom metadata
        schema["x-mtp-gateway"] = {
            "version": schema_version,
            "generated_at": datetime.now(UTC).isoformat(),
            "generator": "mtp-gateway",
        }

    return schema


def export_json_schema_string(
    *,
    version: str | None = None,
    include_metadata: bool = True,
    indent: int = 2,
) -> str:
    """Export GatewayConfig as formatted JSON Schema string.

    Args:
        version: Schema version to embed. Defaults to SCHEMA_VERSION.
        include_metadata: Whether to include $schema, title, and metadata.
        indent: JSON indentation level.

    Returns:
        Formatted JSON string.
    """
    schema = export_json_schema(version=version, include_metadata=include_metadata)
    return json.dumps(schema, indent=indent, sort_keys=False)


def get_schema_version() -> str:
    """Get the current schema version.

    Returns:
        Schema version string in semver format.
    """
    return SCHEMA_VERSION


def validate_config_against_schema(config_dict: dict[str, Any]) -> list[str]:
    """Validate a configuration dictionary against the schema.

    This uses Pydantic's validation, which provides better error messages
    than JSON Schema validation.

    Args:
        config_dict: Configuration dictionary to validate.

    Returns:
        List of validation error messages. Empty if valid.
    """
    errors: list[str] = []

    try:
        GatewayConfig.model_validate(config_dict)
    except Exception as e:
        # Extract Pydantic validation errors
        if hasattr(e, "errors"):
            for err in e.errors():
                loc = ".".join(str(x) for x in err.get("loc", []))
                msg = err.get("msg", str(err))
                errors.append(f"{loc}: {msg}" if loc else msg)
        else:
            errors.append(str(e))

    return errors
