"""CLI application for MTP Gateway.

Provides commands for:
- run: Start the gateway
- validate: Validate configuration
- generate: Generate MTP manifest
- probe: Test connector connectivity
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer
import yaml
from rich.console import Console
from rich.table import Table

from mtp_gateway import __version__
from mtp_gateway.adapters.northbound.manifest.generator import MTPManifestGenerator
from mtp_gateway.adapters.northbound.nodeset.generator import NodeSetGenerator
from mtp_gateway.adapters.southbound.base import create_connector
from mtp_gateway.config.loader import (
    ConfigurationError,
    generate_example_config,
    load_config,
)
from mtp_gateway.config.schema_export import (
    export_json_schema_string,
    get_schema_version,
    validate_config_against_schema,
)
from mtp_gateway.config.validators import get_validator_for_protocol
from mtp_gateway.main import run_gateway
from mtp_gateway.security.certificates import CertificateManager

if TYPE_CHECKING:
    from mtp_gateway.config.schema import GatewayConfig


def version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        typer.echo(f"mtp-gateway {__version__}")
        raise typer.Exit()


app = typer.Typer(
    name="mtp-gateway",
    help="MTP Gateway - Bridging legacy PLCs to MTP-compliant OPC UA",
    add_completion=False,
)


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            "-V",
            callback=version_callback,
            is_eager=True,
            help="Show version and exit",
        ),
    ] = False,
) -> None:
    """MTP Gateway CLI."""
    pass

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
        Path | None,
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
    # Set log environment variables before importing modules
    os.environ["MTP_LOG_LEVEL"] = log_level
    os.environ["MTP_LOG_FORMAT"] = log_format

    console.print("[bold green]Starting MTP Gateway[/bold green]")
    console.print(f"Configuration: {config}")

    try:
        asyncio.run(run_gateway(config, override_path=override))
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
    console.print(f"[bold]Validating:[/bold] {config}")

    try:
        gateway_config = load_config(config)

        console.print("[bold green]Configuration valid![/bold green]")

        if verbose:
            _print_config_summary(gateway_config)

    except ConfigurationError as e:
        console.print("[bold red]Validation failed:[/bold red]")
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


@app.command("generate-nodeset")
def generate_nodeset(
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
            help="Output file path (.xml)",
        ),
    ] = Path("nodeset.xml"),
    deterministic: Annotated[
        bool,
        typer.Option(
            "--deterministic",
            "-d",
            help="Generate deterministic output (fixed timestamps)",
        ),
    ] = False,
) -> None:
    """Generate OPC UA NodeSet2 XML from configuration.

    Creates a NodeSet2 XML file describing the MTP address space.
    This can be imported into other OPC UA servers or tools for
    interoperability testing.
    """
    console.print(f"[bold]Loading configuration:[/bold] {config}")

    gateway_config = load_config(config)

    generator = NodeSetGenerator(gateway_config, deterministic=deterministic)

    output = output.with_suffix(".xml")
    generator.generate(output)

    console.print(f"[bold green]NodeSet2 XML generated:[/bold green] {output}")
    if deterministic:
        console.print("[dim]Generated with deterministic mode (fixed timestamps)[/dim]")


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
        str | None,
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
    example_yaml = generate_example_config()
    output.write_text(example_yaml)

    console.print(f"[bold green]Example configuration written:[/bold green] {output}")
    console.print("\nEdit this file to match your setup, then run:")
    console.print(f"  [cyan]mtp-gateway validate {output}[/cyan]")
    console.print(f"  [cyan]mtp-gateway run {output}[/cyan]")


@app.command()
def version() -> None:
    """Show version information."""
    console.print(f"MTP Gateway version [bold]{__version__}[/bold]")


# Schema subcommand group
schema_app = typer.Typer(
    name="schema",
    help="Configuration schema tools - export, validate, and inspect",
)
app.add_typer(schema_app, name="schema")


@schema_app.command("export")
def schema_export(
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="Output file path (prints to stdout if not specified)",
        ),
    ] = None,
    format_type: Annotated[
        str,
        typer.Option(
            "--format",
            "-f",
            help="Output format (json)",
        ),
    ] = "json",
    version_override: Annotated[
        str | None,
        typer.Option(
            "--version",
            "-v",
            help="Schema version to embed (default: auto)",
        ),
    ] = None,
) -> None:
    """Export the configuration JSON Schema.

    Generates a JSON Schema that can be used for:
    - IDE autocompletion and validation
    - External tooling integration
    - Documentation generation
    """
    if format_type.lower() != "json":
        console.print(f"[bold red]Unsupported format:[/bold red] {format_type}")
        console.print("Currently only 'json' is supported.")
        raise typer.Exit(code=1)

    schema_str = export_json_schema_string(version=version_override, indent=2)

    if output:
        output.write_text(schema_str)
        console.print(f"[bold green]Schema exported:[/bold green] {output}")
        console.print(f"Schema version: {version_override or get_schema_version()}")
    else:
        console.print(schema_str)


@schema_app.command("validate")
def schema_validate(
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
    strict: Annotated[
        bool,
        typer.Option(
            "--strict",
            "-s",
            help="Enable strict validation (validate tag addresses)",
        ),
    ] = False,
) -> None:
    """Validate a configuration file against the schema.

    Performs comprehensive validation including:
    - Schema conformance
    - Reference integrity (tags, connectors)
    - Protocol-specific address validation (with --strict)
    """
    console.print(f"[bold]Validating:[/bold] {config}")

    # Load raw YAML for schema validation
    config_text = config.read_text()
    try:
        config_dict = yaml.safe_load(config_text)
    except yaml.YAMLError as e:
        console.print("[bold red]YAML parse error:[/bold red]")
        console.print(str(e))
        raise typer.Exit(code=1) from e

    # Schema validation
    errors = validate_config_against_schema(config_dict)

    if errors:
        console.print("[bold red]Schema validation failed:[/bold red]")
        for err in errors:
            console.print(f"  [red]•[/red] {err}")
        raise typer.Exit(code=1)

    console.print("[green]✓[/green] Schema validation passed")

    # Strict mode: validate tag addresses
    if strict:
        console.print("\n[bold]Strict validation (protocol addresses):[/bold]")

        # Build connector type lookup
        connector_types: dict[str, str] = {}
        for conn in config_dict.get("connectors", []):
            connector_types[conn.get("name", "")] = conn.get("type", "")

        # Validate each tag's address
        address_errors: list[str] = []
        tags = config_dict.get("tags", [])

        for tag in tags:
            tag_name = tag.get("name", "?")
            address = tag.get("address", "")
            connector_name = tag.get("connector", "")
            connector_type = connector_types.get(connector_name, "")

            validator = get_validator_for_protocol(connector_type)
            if validator:
                result = validator.validate(address)
                if not result.valid:
                    address_errors.append(f"Tag '{tag_name}' ({connector_type}): {result.error}")

        if address_errors:
            console.print("[bold red]Address validation failed:[/bold red]")
            for err in address_errors:
                console.print(f"  [red]•[/red] {err}")
            raise typer.Exit(code=1)

        console.print(f"[green]✓[/green] Validated {len(tags)} tag addresses")

    console.print("\n[bold green]Configuration is valid![/bold green]")


@schema_app.command("version")
def schema_version_cmd() -> None:
    """Show the current schema version."""
    console.print(f"Configuration schema version: [bold]{get_schema_version()}[/bold]")


# Security subcommand group
security_app = typer.Typer(
    name="security",
    help="Security tools - certificate management and security utilities",
)
app.add_typer(security_app, name="security")


@security_app.command("generate-cert")
def security_generate_cert(
    output: Annotated[
        Path,
        typer.Option(
            "--output",
            "-o",
            help="Output directory for certificate and key files",
        ),
    ] = Path("./certs"),
    common_name: Annotated[
        str,
        typer.Option(
            "--common-name",
            "-n",
            help="Common name for the certificate (e.g., hostname)",
        ),
    ] = "MTP-Gateway",
    validity: Annotated[
        int,
        typer.Option(
            "--validity",
            "-v",
            help="Certificate validity in days",
        ),
    ] = 365,
    organization: Annotated[
        str,
        typer.Option(
            "--organization",
            help="Organization name for the certificate",
        ),
    ] = "MTP Gateway",
    application_uri: Annotated[
        str | None,
        typer.Option(
            "--app-uri",
            help="OPC UA application URI",
        ),
    ] = None,
    dns_names: Annotated[
        list[str] | None,
        typer.Option(
            "--dns",
            help="Additional DNS names for Subject Alternative Names",
        ),
    ] = None,
    ip_addresses: Annotated[
        list[str] | None,
        typer.Option(
            "--ip",
            help="IP addresses for Subject Alternative Names",
        ),
    ] = None,
    for_client: Annotated[
        bool,
        typer.Option(
            "--client",
            help="Include client authentication extended key usage",
        ),
    ] = False,
) -> None:
    """Generate a self-signed certificate for OPC UA security.

    Creates a certificate and private key suitable for OPC UA secure
    communication. The certificate includes server authentication by
    default, and optionally client authentication.
    """
    console.print("[bold]Generating self-signed certificate[/bold]")
    console.print(f"  Output directory: {output}")
    console.print(f"  Common name: {common_name}")
    console.print(f"  Validity: {validity} days")

    async def generate() -> tuple[Path, Path]:
        manager = CertificateManager(cert_dir=output)
        return await manager.generate_self_signed(
            common_name=common_name,
            validity_days=validity,
            organization=organization,
            application_uri=application_uri,
            dns_names=dns_names,
            ip_addresses=ip_addresses,
            for_server=True,
            for_client=for_client,
        )

    try:
        cert_path, key_path = asyncio.run(generate())
        console.print("\n[bold green]Certificate generated successfully![/bold green]")
        console.print(f"  Certificate: [cyan]{cert_path}[/cyan]")
        console.print(f"  Private key: [cyan]{key_path}[/cyan]")
        console.print("\nTo use in your configuration:")
        console.print(f"  [dim]cert_path: {cert_path}[/dim]")
        console.print(f"  [dim]key_path: {key_path}[/dim]")
    except Exception as e:
        console.print(f"[bold red]Error generating certificate:[/bold red] {e}")
        raise typer.Exit(code=1) from e


@security_app.command("check-cert")
def security_check_cert(
    cert: Annotated[
        Path,
        typer.Argument(
            help="Path to certificate file to check",
            exists=True,
        ),
    ],
) -> None:
    """Check certificate validity and show certificate information.

    Displays the certificate subject, issuer, validity period,
    and warns if the certificate is expired or expiring soon.
    """
    console.print(f"[bold]Checking certificate:[/bold] {cert}")

    try:
        manager = CertificateManager()
        info = manager.get_certificate_info(cert)
        expiry = manager.check_expiry(cert)

        # Display certificate info
        table = Table(title="Certificate Information")
        table.add_column("Field", style="cyan")
        table.add_column("Value")

        subject = info.get("subject", {})
        table.add_row("Common Name", str(subject.get("commonName", "N/A")))
        table.add_row("Organization", str(subject.get("organizationName", "N/A")))
        table.add_row("Serial Number", str(info.get("serial_number", "N/A")))
        table.add_row("Version", str(info.get("version", "N/A")))
        table.add_row("Not Before", str(info.get("not_valid_before", "N/A")))
        table.add_row("Not After", str(info.get("not_valid_after", "N/A")))

        console.print(table)

        # Check validity
        now = datetime.now(UTC)
        if expiry < now:
            console.print("\n[bold red]⚠ Certificate has EXPIRED![/bold red]")
            raise typer.Exit(code=1)
        elif expiry < now + timedelta(days=30):
            days_left = (expiry - now).days
            console.print(
                f"\n[bold yellow]⚠ Certificate expires in {days_left} days![/bold yellow]"
            )
        else:
            days_left = (expiry - now).days
            console.print(f"\n[green]✓ Certificate valid for {days_left} days[/green]")

    except Exception as e:
        console.print(f"[bold red]Error reading certificate:[/bold red] {e}")
        raise typer.Exit(code=1) from e


def _print_config_summary(config: GatewayConfig) -> None:
    """Print a summary of the configuration."""

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
    console.print("\n[bold]OPC UA Server:[/bold]")
    console.print(f"  Endpoint: {config.opcua.endpoint}")
    console.print(f"  Namespace: {config.opcua.namespace_uri}")


if __name__ == "__main__":
    app()
