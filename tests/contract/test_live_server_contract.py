"""Live server contract tests.

These tests verify that the MTP manifest accurately describes the
actual OPC UA server address space. Critical for POL interoperability.

Each test starts a live OPC UA server and verifies the contract between
the manifest and the server's actual address space.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest
from asyncua import ua

from mtp_gateway.adapters.northbound.manifest.generator import MTPManifestGenerator
from mtp_gateway.adapters.northbound.opcua.server import MTPOPCUAServer
from mtp_gateway.application.tag_manager import TagManager

from .helpers import ContractViolation, ManifestParser, OPCUABrowser, compare_manifest_to_server

if TYPE_CHECKING:
    from asyncua import Client

    from mtp_gateway.config.schema import GatewayConfig


@pytest.mark.contract
class TestLiveServerContract:
    """Contract tests verifying manifest matches live server."""

    async def test_all_manifest_node_ids_exist_in_server(
        self,
        opcua_server: MTPOPCUAServer,
        opcua_client: Client,
        manifest_generator: MTPManifestGenerator,
        contract_config: GatewayConfig,
    ) -> None:
        """All node IDs in the manifest must exist in the server.

        This is the fundamental contract: if the manifest says a node
        exists, it must actually exist in the server for POL integration.
        """
        # Get manifest node IDs
        manifest_node_ids = set(manifest_generator.get_all_node_ids())

        # Browse server to get actual node IDs
        browser = OPCUABrowser(opcua_client, contract_config)
        server_node_ids = await browser.browse_all_node_ids()

        # Check each manifest node exists in server
        violations = compare_manifest_to_server(manifest_node_ids, server_node_ids)

        if violations:
            violation_details = "\n".join(str(v) for v in violations)
            pytest.fail(
                f"Contract violations found ({len(violations)}):\n{violation_details}"
            )

    async def test_manifest_data_types_match_server(
        self,
        opcua_server: MTPOPCUAServer,
        opcua_client: Client,
        manifest_generator: MTPManifestGenerator,
        contract_config: GatewayConfig,
    ) -> None:
        """Manifest node data types must match server VariantTypes.

        The manifest declares expected types. The server must expose
        nodes with compatible OPC UA data types.
        """
        # Get manifest node IDs
        manifest_node_ids = manifest_generator.get_all_node_ids()

        browser = OPCUABrowser(opcua_client, contract_config)

        # Verify each manifest node has correct type
        type_mismatches: list[str] = []

        for node_id in manifest_node_ids:
            if not await browser.verify_node_exists(node_id):
                continue  # Missing node - caught by other test

            # Parse node ID to check type
            # Service state variables should be UInt32
            if "StateCur" in node_id or "CommandOp" in node_id:
                expected_type = "UInt32"
            elif "ProcedureCur" in node_id or "ProcedureReq" in node_id:
                expected_type = "UInt32"
            else:
                # Data assembly values can be various types
                continue  # Skip type checking for data assemblies

            # Get actual type from server
            nodes_with_types = await browser.browse_nodes_with_types()
            if node_id in nodes_with_types:
                actual_type = nodes_with_types[node_id]
                if actual_type != expected_type:
                    type_mismatches.append(
                        f"  {node_id}: expected {expected_type}, got {actual_type}"
                    )

        if type_mismatches:
            pytest.fail(
                f"Data type mismatches:\n" + "\n".join(type_mismatches)
            )

    async def test_service_state_machine_nodes_browsable(
        self,
        opcua_server: MTPOPCUAServer,
        opcua_client: Client,
        contract_config: GatewayConfig,
    ) -> None:
        """Service state machine nodes must be browsable and accessible.

        For each service, the following nodes must exist:
        - CommandOp (writable)
        - StateCur (readable)
        - ProcedureCur (readable)
        - ProcedureReq (writable)
        """
        browser = OPCUABrowser(opcua_client, contract_config)
        pea_name = f"PEA_{contract_config.gateway.name}"
        ns_uri = contract_config.opcua.namespace_uri

        missing_nodes: list[str] = []
        access_errors: list[str] = []

        for service in contract_config.mtp.services:
            service_base = f"{pea_name}.Services.{service.name}"

            required_nodes = [
                f"nsu={ns_uri};s={service_base}.CommandOp",
                f"nsu={ns_uri};s={service_base}.StateCur",
                f"nsu={ns_uri};s={service_base}.ProcedureCur",
                f"nsu={ns_uri};s={service_base}.ProcedureReq",
            ]

            for node_id in required_nodes:
                exists = await browser.verify_node_exists(node_id)
                if not exists:
                    missing_nodes.append(f"  {node_id}")
                else:
                    # Try to read the value (verifies access)
                    try:
                        await browser.get_node_value(node_id)
                    except Exception as e:
                        access_errors.append(f"  {node_id}: {e}")

        errors: list[str] = []
        if missing_nodes:
            errors.append(f"Missing service nodes:\n" + "\n".join(missing_nodes))
        if access_errors:
            errors.append(f"Access errors:\n" + "\n".join(access_errors))

        if errors:
            pytest.fail("\n\n".join(errors))

    async def test_data_assembly_structure_matches_manifest(
        self,
        opcua_server: MTPOPCUAServer,
        opcua_client: Client,
        manifest_generator: MTPManifestGenerator,
        contract_config: GatewayConfig,
    ) -> None:
        """Data assembly structure must match between manifest and server.

        Each data assembly should have its declared bindings as
        accessible nodes in the server.
        """
        browser = OPCUABrowser(opcua_client, contract_config)
        pea_name = f"PEA_{contract_config.gateway.name}"
        ns_uri = contract_config.opcua.namespace_uri

        missing_bindings: list[str] = []

        for da in contract_config.mtp.data_assemblies:
            da_base = f"{pea_name}.DataAssemblies.{da.name}"

            for binding_name in da.bindings:
                node_id = f"nsu={ns_uri};s={da_base}.{binding_name}"
                exists = await browser.verify_node_exists(node_id)
                if not exists:
                    missing_bindings.append(
                        f"  {da.name}.{binding_name} ({node_id})"
                    )

        if missing_bindings:
            pytest.fail(
                f"Missing data assembly bindings:\n" + "\n".join(missing_bindings)
            )

    async def test_node_id_stability_across_restarts(
        self,
        contract_config: GatewayConfig,
        tag_manager: TagManager,
    ) -> None:
        """Same configuration must produce same NodeIds across restarts.

        This tests determinism: if you restart the gateway with the
        same config, all NodeIds must be identical. This is critical
        for POL systems that cache NodeId references.
        """
        async def start_server_and_collect_node_ids() -> set[str]:
            """Start server and return all node IDs."""
            server = MTPOPCUAServer(
                config=contract_config,
                tag_manager=tag_manager,
            )
            await server.start()
            await asyncio.sleep(0.1)

            try:
                node_ids = set(server.get_all_node_ids())
                return node_ids
            finally:
                await server.stop()

        # Start server twice and compare node IDs
        node_ids_run1 = await start_server_and_collect_node_ids()

        # Small delay between runs
        await asyncio.sleep(0.1)

        node_ids_run2 = await start_server_and_collect_node_ids()

        # Compare
        only_in_run1 = node_ids_run1 - node_ids_run2
        only_in_run2 = node_ids_run2 - node_ids_run1

        if only_in_run1 or only_in_run2:
            errors: list[str] = []
            if only_in_run1:
                errors.append(f"Only in run 1: {only_in_run1}")
            if only_in_run2:
                errors.append(f"Only in run 2: {only_in_run2}")
            pytest.fail(
                f"NodeIds not stable across restarts:\n" + "\n".join(errors)
            )


@pytest.mark.contract
class TestManifestXMLContract:
    """Contract tests for manifest XML structure."""

    async def test_manifest_xml_is_valid(
        self,
        manifest_generator: MTPManifestGenerator,
    ) -> None:
        """Generated manifest must be valid XML."""
        manifest_xml = manifest_generator.generate()

        # Parse the XML to verify it's valid
        parser = ManifestParser(manifest_xml)
        node_ids = parser.get_all_node_ids()

        # Should have extracted some node IDs
        assert len(node_ids) > 0, "Manifest should contain node IDs"

    async def test_manifest_contains_all_data_assemblies(
        self,
        manifest_generator: MTPManifestGenerator,
        contract_config: GatewayConfig,
    ) -> None:
        """Manifest must reference all configured data assemblies."""
        manifest_xml = manifest_generator.generate()
        parser = ManifestParser(manifest_xml)
        node_ids = parser.get_all_node_ids()

        pea_name = f"PEA_{contract_config.gateway.name}"

        for da in contract_config.mtp.data_assemblies:
            # Check at least one node ID contains the data assembly name
            matching = [nid for nid in node_ids if f".{da.name}." in nid]
            assert matching, (
                f"Data assembly '{da.name}' not found in manifest node IDs"
            )

    async def test_manifest_contains_all_services(
        self,
        manifest_generator: MTPManifestGenerator,
        contract_config: GatewayConfig,
    ) -> None:
        """Manifest must reference all configured services."""
        manifest_xml = manifest_generator.generate()
        parser = ManifestParser(manifest_xml)
        node_ids = parser.get_all_node_ids()

        for service in contract_config.mtp.services:
            # Check service nodes exist
            matching = [nid for nid in node_ids if f".{service.name}." in nid]
            assert matching, (
                f"Service '{service.name}' not found in manifest node IDs"
            )


@pytest.mark.contract
class TestServerAddressSpace:
    """Contract tests for server address space structure."""

    async def test_server_has_pea_root_node(
        self,
        opcua_server: MTPOPCUAServer,
        opcua_client: Client,
        contract_config: GatewayConfig,
    ) -> None:
        """Server must have PEA root node under Objects."""
        pea_name = f"PEA_{contract_config.gateway.name}"

        objects = opcua_client.get_objects_node()
        children = await objects.get_children()

        pea_found = False
        for child in children:
            browse_name = await child.read_browse_name()
            if browse_name.Name == pea_name:
                pea_found = True
                break

        assert pea_found, f"PEA root node '{pea_name}' not found in Objects"

    async def test_server_has_data_assemblies_folder(
        self,
        opcua_server: MTPOPCUAServer,
        opcua_client: Client,
        contract_config: GatewayConfig,
    ) -> None:
        """Server must have DataAssemblies folder under PEA."""
        pea_name = f"PEA_{contract_config.gateway.name}"

        objects = opcua_client.get_objects_node()
        children = await objects.get_children()

        # Find PEA
        pea_node = None
        for child in children:
            browse_name = await child.read_browse_name()
            if browse_name.Name == pea_name:
                pea_node = child
                break

        assert pea_node is not None, "PEA node not found"

        # Find DataAssemblies
        pea_children = await pea_node.get_children()
        da_found = False
        for child in pea_children:
            browse_name = await child.read_browse_name()
            if browse_name.Name == "DataAssemblies":
                da_found = True
                break

        assert da_found, "DataAssemblies folder not found under PEA"

    async def test_server_has_services_folder(
        self,
        opcua_server: MTPOPCUAServer,
        opcua_client: Client,
        contract_config: GatewayConfig,
    ) -> None:
        """Server must have Services folder under PEA."""
        pea_name = f"PEA_{contract_config.gateway.name}"

        objects = opcua_client.get_objects_node()
        children = await objects.get_children()

        # Find PEA
        pea_node = None
        for child in children:
            browse_name = await child.read_browse_name()
            if browse_name.Name == pea_name:
                pea_node = child
                break

        assert pea_node is not None, "PEA node not found"

        # Find Services
        pea_children = await pea_node.get_children()
        svc_found = False
        for child in pea_children:
            browse_name = await child.read_browse_name()
            if browse_name.Name == "Services":
                svc_found = True
                break

        assert svc_found, "Services folder not found under PEA"
