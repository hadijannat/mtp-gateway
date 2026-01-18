"""Configuration loading and validation for MTP Gateway."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from pathlib import Path

import structlog
import yaml
from pydantic import ValidationError

from mtp_gateway.config.schema import GatewayConfig

logger = structlog.get_logger(__name__)


class ConfigurationError(Exception):
    """Raised when configuration loading or validation fails."""

    def __init__(self, message: str, errors: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or []


def load_yaml_file(path: Path) -> dict[str, Any]:
    """Load a YAML file and return its contents as a dictionary.

    Args:
        path: Path to the YAML file

    Returns:
        Dictionary containing the parsed YAML

    Raises:
        ConfigurationError: If the file cannot be read or parsed
    """
    if not path.exists():
        raise ConfigurationError(f"Configuration file not found: {path}")

    if not path.is_file():
        raise ConfigurationError(f"Configuration path is not a file: {path}")

    try:
        with path.open("r", encoding="utf-8") as f:
            content = yaml.safe_load(f)
            if content is None:
                return {}
            if not isinstance(content, dict):
                raise ConfigurationError(
                    f"Configuration must be a YAML mapping, got {type(content)}"
                )
            return content
    except yaml.YAMLError as e:
        raise ConfigurationError(f"Invalid YAML in {path}: {e}") from e
    except OSError as e:
        raise ConfigurationError(f"Cannot read configuration file {path}: {e}") from e


def expand_env_vars(config: dict[str, Any]) -> dict[str, Any]:
    """Recursively expand environment variables in string values.

    Supports ${VAR} and ${VAR:-default} syntax.

    Args:
        config: Configuration dictionary

    Returns:
        Configuration with environment variables expanded
    """

    def expand_value(value: Any) -> Any:
        if isinstance(value, str):
            # Expand ${VAR} and ${VAR:-default} patterns
            return os.path.expandvars(value)
        elif isinstance(value, dict):
            return {k: expand_value(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [expand_value(item) for item in value]
        return value

    return cast("dict[str, Any]", expand_value(config))


def merge_configs(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep merge two configuration dictionaries.

    Override values take precedence. Lists are replaced, not merged.

    Args:
        base: Base configuration
        override: Override configuration

    Returns:
        Merged configuration
    """
    result = base.copy()

    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_configs(result[key], value)
        else:
            result[key] = value

    return result


def load_config(
    config_path: Path,
    *,
    override_path: Path | None = None,
    expand_env: bool = True,
) -> GatewayConfig:
    """Load and validate gateway configuration from YAML file(s).

    Args:
        config_path: Path to the main configuration file
        override_path: Optional path to override configuration file
        expand_env: Whether to expand environment variables

    Returns:
        Validated GatewayConfig instance

    Raises:
        ConfigurationError: If configuration is invalid
    """
    logger.info("Loading configuration", path=str(config_path))

    # Load main config
    config_dict = load_yaml_file(config_path)

    # Load and merge override if provided
    if override_path:
        logger.info("Loading configuration override", path=str(override_path))
        override_dict = load_yaml_file(override_path)
        config_dict = merge_configs(config_dict, override_dict)

    # Expand environment variables
    if expand_env:
        config_dict = expand_env_vars(config_dict)

    # Validate with Pydantic
    try:
        config = GatewayConfig.model_validate(config_dict)
    except ValidationError as e:
        errors = cast("list[dict[str, Any]]", e.errors())
        error_messages = []
        for error in errors:
            loc = ".".join(str(x) for x in error["loc"])
            msg = error["msg"]
            error_messages.append(f"  - {loc}: {msg}")

        raise ConfigurationError(
            "Configuration validation failed:\n" + "\n".join(error_messages),
            errors=errors,
        ) from e

    logger.info(
        "Configuration loaded successfully",
        gateway_name=config.gateway.name,
        connectors=len(config.connectors),
        tags=len(config.tags),
        data_assemblies=len(config.mtp.data_assemblies),
        services=len(config.mtp.services),
    )

    return config


def validate_config_file(config_path: Path) -> list[str]:
    """Validate a configuration file without loading it.

    Args:
        config_path: Path to the configuration file

    Returns:
        List of validation error messages (empty if valid)
    """
    errors: list[str] = []

    try:
        load_config(config_path)
    except ConfigurationError as e:
        errors.append(str(e))

    return errors


def generate_example_config() -> str:
    """Generate an example configuration YAML string.

    Returns:
        YAML string with example configuration
    """
    example = {
        "gateway": {
            "name": "Reactor_PEA_01",
            "version": "1.0.0",
            "description": "Example MTP Gateway for Reactor Module",
        },
        "opcua": {
            "endpoint": "opc.tcp://0.0.0.0:4840",
            "namespace_uri": "urn:example:reactor-pea",
            "security": {
                "allow_none": True,
                "policies": ["Basic256Sha256_SignAndEncrypt"],
            },
        },
        "connectors": [
            {
                "name": "plc_modbus",
                "type": "modbus_tcp",
                "host": "192.168.1.100",
                "port": 502,
                "unit_id": 1,
                "poll_interval_ms": 500,
            }
        ],
        "tags": [
            {
                "name": "reactor_temp",
                "connector": "plc_modbus",
                "address": "40001",
                "datatype": "float32",
                "scale": {"gain": 0.1, "offset": 0},
                "unit": "degC",
                "description": "Reactor temperature",
            },
            {
                "name": "inlet_valve",
                "connector": "plc_modbus",
                "address": "00001",
                "datatype": "bool",
                "writable": True,
                "description": "Inlet valve control",
            },
        ],
        "mtp": {
            "data_assemblies": [
                {
                    "name": "TempSensor_01",
                    "type": "AnaView",
                    "bindings": {"V": "reactor_temp"},
                    "v_scl_min": 0.0,
                    "v_scl_max": 200.0,
                    "v_unit": 1001,
                },
                {
                    "name": "InletValve_01",
                    "type": "BinVlv",
                    "bindings": {"V": "inlet_valve"},
                },
            ],
            "services": [
                {
                    "name": "Dosing",
                    "mode": "thin_proxy",
                    "state_cur_tag": "dosing_state",
                    "command_op_tag": "dosing_cmd",
                    "procedures": [{"id": 1, "name": "DoseProduct", "is_default": True}],
                }
            ],
        },
        "safety": {
            "write_allowlist": ["inlet_valve"],
            "safe_state_outputs": [{"tag": "inlet_valve", "value": False}],
            "command_rate_limit": "10/s",
        },
    }

    return yaml.dump(example, default_flow_style=False, sort_keys=False, allow_unicode=True)
