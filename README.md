# MTP Gateway

Production-grade gateway bridging legacy PLCs to MTP-compliant OPC UA interface.

## Overview

MTP Gateway connects brownfield industrial PLCs to modern Process Orchestration Layers (POLs) by:

- **Southbound Adapters**: Connect to PLCs via Modbus TCP/RTU, Siemens S7, EtherNet/IP, or OPC UA
- **Northbound Interface**: Expose an MTP-compliant OPC UA address space following VDI/VDE/NAMUR 2658
- **Manifest Generation**: Generate AutomationML manifests for POL import
- **Proxy Modes**: Support Thin, Thick, and Hybrid proxy configurations

## Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/example/mtp-gateway.git
cd mtp-gateway

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# or: .venv\Scripts\activate  # Windows

# Install in development mode
pip install -e ".[dev]"
```

### Generate Example Configuration

```bash
mtp-gateway generate-example -o config.yaml
```

### Validate Configuration

```bash
mtp-gateway validate config.yaml -v
```

### Run the Gateway

```bash
mtp-gateway run config.yaml
```

### Generate MTP Manifest

```bash
mtp-gateway generate-manifest config.yaml -o module.aml
# Or generate a complete MTP package:
mtp-gateway generate-manifest config.yaml -o module.mtp --package
```

## Configuration

Configuration is done via YAML files. See `examples/` for sample configurations.

### Basic Structure

```yaml
gateway:
  name: Reactor_PEA_01
  version: "1.0.0"

opcua:
  endpoint: opc.tcp://0.0.0.0:4840
  namespace_uri: urn:example:reactor-pea

connectors:
  - name: plc_modbus
    type: modbus_tcp
    host: 192.168.1.100
    port: 502

tags:
  - name: reactor_temp
    connector: plc_modbus
    address: "40001"
    datatype: float32
    unit: degC

mtp:
  data_assemblies:
    - name: TempSensor_01
      type: AnaView
      bindings:
        V: reactor_temp
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    NORTHBOUND ADAPTERS                          │
│  ┌─────────────────┐  ┌─────────────────────────────────────┐  │
│  │  OPC UA Server  │  │  MTP Manifest Generator (AML/CAEX) │  │
│  └────────┬────────┘  └──────────────────┬──────────────────┘  │
├───────────┴──────────────────────────────┴──────────────────────┤
│                        APPLICATION CORE                          │
│  Tag Manager │ Service Manager │ Data Assembly Registry          │
├─────────────────────────────────────────────────────────────────┤
│                    SOUTHBOUND ADAPTERS                           │
│  Modbus TCP/RTU │ S7 (Snap7) │ EtherNet/IP │ OPC UA Client      │
└─────────────────────────────────────────────────────────────────┘
```

## Supported Protocols

| Protocol | Status | Library |
|----------|--------|---------|
| Modbus TCP | ✅ Ready | pymodbus |
| Modbus RTU | ✅ Ready | pymodbus |
| Siemens S7 | 🔄 Planned | python-snap7 |
| EtherNet/IP | 🔄 Planned | pycomm3 |
| OPC UA Client | 🔄 Planned | asyncua |

## Data Assembly Types

Following VDI 2658-4:

| Type | Description |
|------|-------------|
| AnaView | Read-only analog value |
| BinView | Read-only binary value |
| DIntView | Read-only integer value |
| AnaServParam | Writable analog parameter |
| BinServParam | Writable binary parameter |
| BinVlv | Binary valve control |
| AnaVlv | Analog valve control |
| PIDCtrl | PID controller |

## Development

### Run Tests

```bash
# Unit tests
pytest tests/unit -v

# Integration tests (requires Modbus simulator)
docker run -d -p 5020:5020 oitc/modbus-server
pytest tests/integration -v

# All tests with coverage
pytest --cov=src/mtp_gateway --cov-report=html
```

### Code Quality

```bash
# Lint and format
ruff check src/ tests/
ruff format src/ tests/

# Type checking
mypy src/

# Run all checks
pre-commit run --all-files
```

## Docker

### Build

```bash
docker build -t mtp-gateway -f docker/Dockerfile .
```

### Run

```bash
docker run -p 4840:4840 -v ./config.yaml:/config/config.yaml mtp-gateway
```

### Docker Compose

```bash
docker compose -f docker/docker-compose.yaml up
```

## License

MIT
