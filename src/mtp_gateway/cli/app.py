"""CLI application for MTP Gateway.

Provides commands for:
- run: Start the gateway
- validate: Validate configuration
- generate: Generate MTP manifest
- probe: Test connector connectivity
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="mtp-gateway",
    help="MTP Gateway - Bridging legacy PLCs to MTP-compliant OPC UA",
    add_completion=False,
)

console = Console()


@app.command()
def run(
    config: Annotated[
        Path,
        typer.Argument(
            help="Path to configuration YAML file",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
        ),
    ],
    override: Annotated[
        Optional[Path],
        typer.Option(
            "--override",
            "-o",
            help="Path to override configuration file",
            exists=True,
        ),
    ] = None,
    log_level: Annotated[
        str,
        typer.Option(
            "--log-level",
            "-l",
            help="Log level (DEBUG, INFO, WARNING, ERROR)",
        ),
    ] = "INFO",
    log_format: Annotated[
        str,
        typer.Option(
            "--log-format",
            help="Log format (console, json)",
        ),
    ] = "console",
) -> None:
    """Start the MTP Gateway.

    Loads configuration, initializes connectors, and starts the OPC UA server.
    """
    import asyncio
    import os

    # Set log environment variables before importing modules
    os.environ["MTP_LOG_LEVEL"] = log_level
    os.environ["MTP_LOG_FORMAT"] = log_format

    from mtp_gateway.main import run_gateway

    console.print(f"[bold green]Starting MTP Gateway[/bold green]")
    console.print(f"Configuration: {config}")

    try:
        asyncio.run(run_gateway(config))
    except KeyboardInterrupt:
        console.print("\n[yellow]Shutdown requested[/yellow]")
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(code=1) from e


@app.command()
def validate(
    config: Annotated[
        Path,
        typer.Argument(
            help="Path to configuration YAML file",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
        ),
    ],
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            "-v",
            help="Show detailed validation information",
        ),
    ] = False,
) -> None:
    """Validate a configuration file.

    Checks the configuration for errors without starting the gateway.
    """
    from mtp_gateway.config.loader import ConfigurationError, load_config

    console.print(f"[bold]Validating:[/bold] {config}")

    try:
        gateway_config = load_config(config)

        console.print("[bold green]Configuration valid![/bold green]")

        if verbose:
            _print_config_summary(gateway_config)

    except ConfigurationError as e:
        console.print(f"[bold red]Validation failed:[/bold red]")
        console.print(str(e))
        raise typer.Exit(code=1) from e


@app.command("generate-manifest")
def generate_manifest(
    config: Annotated[
        Path,
        typer.Argument(
            help="Path to configuration YAML file",
            exists=True,
        ),
    ],
    output: Annotated[
        Path,
        typer.Option(
            "--output",
            "-o",
            help="Output file path (.aml or .mtp)",
        ),
    ] = Path("manifest.aml"),
    package: Annotated[
        bool,
        typer.Option(
            "--package",
            "-p",
            help="Generate MTP package (.mtp) instead of raw manifest",
        ),
    ] = False,
) -> None:
    """Generate MTP manifest from configuration.

    Creates an AutomationML manifest file that can be imported into
    a Process Orchestration Layer (POL).
    """
    from mtp_gateway.adapters.northbound.manifest.generator import (
        MTPManifestGenerator,
    )
    from mtp_gateway.config.loader import load_config

    console.print(f"[bold]Loading configuration:[/bold] {config}")

    gateway_config = load_config(config)

    generator = MTPManifestGenerator(gateway_config)

    if package:
        output = output.with_suffix(".mtp")
        generator.generate_package(output)
        console.print(f"[bold green]MTP package generated:[/bold green] {output}")
    else:
        output = output.with_suffix(".aml")
        generator.generate(output)
        console.print(f"[bold green]Manifest generated:[/bold green] {output}")


@app.command()
def probe(
    config: Annotated[
        Path,
        typer.Argument(
            help="Path to configuration YAML file",
            exists=True,
        ),
    ],
    connector: Annotated[
        Optional[str],
        typer.Option(
            "--connector",
            "-c",
            help="Specific connector to probe (probes all if not specified)",
        ),
    ] = None,
) -> None:
    """Test connectivity to configured PLCs.

    Attempts to connect to each connector and reports status.
    """
    import asyncio

    from mtp_gateway.adapters.southbound.base import create_connector
    from mtp_gateway.config.loader import load_config

    console.print(f"[bold]Loading configuration:[/bold] {config}")
    gateway_config = load_config(config)

    connectors_to_probe = gateway_config.connectors
    if connector:
        connectors_to_probe = [c for c in connectors_to_probe if c.name == connector]
        if not connectors_to_probe:
            console.print(f"[bold red]Connector not found:[/bold red] {connector}")
            raise typer.Exit(code=1)

    async def probe_connectors() -> None:
        table = Table(title="Connector Status")
        table.add_column("Connector", style="cyan")
        table.add_column("Type", style="magenta")
        table.add_column("Status", style="green")
        table.add_column("Details")

        for conn_config in connectors_to_probe:
            try:
                conn = create_connector(conn_config)
                await conn.connect()
                health = conn.health_status()
                await conn.disconnect()

                status = "[green]Connected[/green]"
                details = f"Errors: {health.total_errors}"
            except Exception as e:
                status = "[red]Failed[/red]"
                details = str(e)[:50]

            table.add_row(
                conn_config.name,
                conn_config.type.value,
                status,
                details,
            )

        console.print(table)

    asyncio.run(probe_connectors())


@app.command("generate-example")
def generate_example(
    output: Annotated[
        Path,
        typer.Option(
            "--output",
            "-o",
            help="Output file path",
        ),
    ] = Path("example-config.yaml"),
) -> None:
    """Generate an example configuration file.

    Creates a sample configuration that can be customized for your setup.
    """
    from mtp_gateway.config.loader import generate_example_config

    example_yaml = generate_example_config()
    output.write_text(example_yaml)

    console.print(f"[bold green]Example configuration written:[/bold green] {output}")
    console.print("\nEdit this file to match your setup, then run:")
    console.print(f"  [cyan]mtp-gateway validate {output}[/cyan]")
    console.print(f"  [cyan]mtp-gateway run {output}[/cyan]")


@app.command()
def version() -> None:
    """Show version information."""
    from mtp_gateway import __version__

    console.print(f"MTP Gateway version [bold]{__version__}[/bold]")


def _print_config_summary(config: "GatewayConfig") -> None:
    """Print a summary of the configuration."""
    from mtp_gateway.config.schema import GatewayConfig

    table = Table(title="Configuration Summary")
    table.add_column("Component", style="cyan")
    table.add_column("Count", style="green")
    table.add_column("Details")

    table.add_row(
        "Gateway",
        "1",
        f"{config.gateway.name} v{config.gateway.version}",
    )
    table.add_row(
        "Connectors",
        str(len(config.connectors)),
        ", ".join(c.name for c in config.connectors),
    )
    table.add_row(
        "Tags",
        str(len(config.tags)),
        f"{sum(1 for t in config.tags if t.writable)} writable",
    )
    table.add_row(
        "Data Assemblies",
        str(len(config.mtp.data_assemblies)),
        "",
    )
    table.add_row(
        "Services",
        str(len(config.mtp.services)),
        ", ".join(s.name for s in config.mtp.services),
    )

    console.print(table)

    # OPC UA info
    console.print(f"\n[bold]OPC UA Server:[/bold]")
    console.print(f"  Endpoint: {config.opcua.endpoint}")
    console.print(f"  Namespace: {config.opcua.namespace_uri}")


if __name__ == "__main__":
    app()
