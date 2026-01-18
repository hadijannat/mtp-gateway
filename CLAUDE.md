# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Test Commands

```bash
# Install in development mode
pip install -e ".[dev]"

# Run all unit tests
pytest tests/unit/ -v -p no:schemathesis

# Run a single test file
pytest tests/unit/test_interlocks.py -v

# Run a single test
pytest tests/unit/test_interlocks.py::TestInterlockEvaluator::test_element_interlocked_when_condition_true -v

# Lint and format
ruff check src/ tests/
ruff format src/ tests/

# Type checking
mypy src/

# Run all pre-commit checks
pre-commit run --all-files
```

## Architecture Overview

MTP Gateway bridges legacy PLCs to MTP-compliant OPC UA interfaces following VDI/VDE/NAMUR 2658.

### Layer Structure

```
Northbound (OPC UA Server, Manifest Generator)
    ↕
Application Core (TagManager, ServiceManager)
    ↕
Southbound (Modbus, S7, EtherNet/IP, OPC UA Client)
```

### Key Components

**Application Layer** (`application/`)
- `TagManager` - Central hub for all tag read/write operations with subscriptions
- `ServiceManager` - Orchestrates service lifecycle with PackML state machine, handles interlock enforcement

**Domain Layer** (`domain/`)
- `model/data_assemblies.py` - Data Assembly types per VDI 2658-4 (AnaView, BinVlv, AnaMon, etc.)
- `model/tags.py` - TagValue with quality and timestamps
- `state_machine/packml.py` - PackML state machine (IDLE→STARTING→EXECUTE→COMPLETING→COMPLETE)
- `rules/interlocks.py` - InterlockEvaluator for blocking dangerous operations
- `rules/safety.py` - SafetyController with write allowlist and rate limiting

**Adapters** (`adapters/`)
- `southbound/` - PLC drivers (Modbus, S7, EIP, OPC UA Client) extend `BaseConnector`
- `northbound/opcua/` - OPC UA server exposing MTP address space
- `northbound/manifest/` - AutomationML manifest generator
- `persistence/` - SQLite-based state persistence for recovery

### Proxy Modes

| Mode | State Machine | Behavior |
|------|---------------|----------|
| THIN | In PLC | Gateway writes commands, polls state |
| THICK | In Gateway | Gateway runs state machine, executes hooks |
| HYBRID | Both | Writes to PLC + local tracking |

### Interlock Enforcement

Interlocks block START/UNHOLD commands when safety conditions are active. ABORT/STOP are never blocked (safety priority). Configured via `interlock_binding` on DataAssemblyConfig.

### Configuration

YAML-based configuration validated by Pydantic models in `config/schema.py`. Key sections:
- `gateway` - Name and version
- `opcua` - Server endpoint and security
- `connectors` - Southbound PLC connections
- `tags` - Tag definitions with addresses
- `mtp.data_assemblies` - VDI 2658-4 data assemblies
- `mtp.services` - Service definitions with procedures

## Testing Patterns

Tests use pytest-asyncio with `asyncio_mode = "auto"`. Mocks are common for TagManager and PLC drivers. Follow TDD: write failing tests first, then implement.
