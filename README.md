# MTP Gateway

Bridges brownfield PLCs to an MTP-compliant OPC UA interface, with deterministic
NodeIds and AutomationML manifest generation for plug-and-produce integration.

[![CI](https://github.com/hadijannat/mtp-gateway/actions/workflows/ci.yaml/badge.svg)](https://github.com/hadijannat/mtp-gateway/actions/workflows/ci.yaml)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

## At a glance

- **Southbound**: Modbus TCP/RTU, Siemens S7, EtherNet/IP, OPC UA Client
- **Northbound**: OPC UA server with MTP address space + AutomationML manifest
- **Proxy modes**: Thin, Thick, Hybrid per service
- **Operationally safe**: write allowlists, rate limits, quality propagation
- **Deterministic**: stable NodeIds across restarts from config

## Who this is for

- **Controls & automation** teams integrating legacy PLCs with modern POLs
- **System integrators** who need repeatable, configuration-driven rollouts
- **Software teams** building industrial edge products with clean architecture

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                           NORTHBOUND                                │
│     OPC UA Server (MTP Address Space) + AutomationML Manifest        │
├─────────────────────────────────────────────────────────────────────┤
│                             CORE                                    │
│   Tag Model · Mapping Engine · Service Engine · Safety & Interlocks  │
├─────────────────────────────────────────────────────────────────────┤
│                           SOUTHBOUND                                │
│      Modbus TCP/RTU · S7 · EtherNet/IP · OPC UA Client               │
└─────────────────────────────────────────────────────────────────────┘
```

## Quick start

```bash
git clone https://github.com/hadijannat/mtp-gateway.git
cd mtp-gateway

python -m venv .venv
source .venv/bin/activate

pip install -e ".[dev]"
```

Generate a config, validate, run:

```bash
mtp-gateway generate-example -o config.yaml
mtp-gateway validate config.yaml
mtp-gateway run config.yaml
```

Generate an AutomationML manifest or an MTP package:

```bash
mtp-gateway generate-manifest config.yaml -o module.aml
mtp-gateway generate-manifest config.yaml -o module.mtp --package
```

Probe PLC connectivity:

```bash
mtp-gateway probe config.yaml
mtp-gateway probe config.yaml --connector reactor_plc
```

## Configuration overview

MTP Gateway is configuration-driven. See `examples/reactor-pea.yaml` for a full
reference. The essentials:

```yaml
gateway:
  name: Reactor_PEA_01
  version: "1.0.0"
  vendor: Hadijannat
  vendor_url: https://github.com/hadijannat/mtp-gateway

opcua:
  endpoint: opc.tcp://0.0.0.0:4840
  namespace_uri: urn:example:reactor-pea
  security:
    allow_none: false

connectors:
  - name: reactor_plc
    type: modbus_tcp
    host: 192.168.1.100
    port: 502

tags:
  - name: reactor_temp
    connector: reactor_plc
    address: "40001"
    datatype: float32
    byte_order: big
    word_order: big
    unit: degC

mtp:
  data_assemblies:
    - name: TempSensor_Reactor
      type: AnaView
      bindings:
        V: reactor_temp
  services:
    - name: Dosing
      mode: thin_proxy
      state_cur_tag: dosing_state
      command_op_tag: dosing_cmd

safety:
  write_allowlist:
    - dosing_cmd
```

## CLI commands

- `mtp-gateway run <config.yaml>`: start the gateway
- `mtp-gateway validate <config.yaml>`: validate configuration
- `mtp-gateway generate-manifest <config.yaml> -o <file>`: generate AML/MTP
- `mtp-gateway probe <config.yaml>`: test connector connectivity
- `mtp-gateway generate-example`: create a starter config
- `mtp-gateway version`: show version

## Protocols & drivers

| Protocol | Status | Notes |
| --- | --- | --- |
| Modbus TCP/RTU | Ready | Included by default |
| Siemens S7 | Ready | Install with `.[s7]` |
| EtherNet/IP | Ready | Install with `.[eip]` |
| OPC UA Client | Ready | Included by default |

## Testing & quality

```bash
pytest -q
ruff check src/ tests/
ruff format src/ tests/
mypy src/
pre-commit run --all-files
```

## Docker

```bash
docker build -t mtp-gateway -f docker/Dockerfile .
docker run -p 4840:4840 -v ./config.yaml:/config/config.yaml mtp-gateway
docker compose -f docker/docker-compose.yaml up
```

## License

MIT
