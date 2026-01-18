"""Service endpoints router.

Provides endpoints for service state and command operations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from fastapi import APIRouter, Depends, HTTPException, status

from mtp_gateway.adapters.northbound.webui.dependencies import (
    CurrentUserDep,
    ServiceManagerDep,
    require_permission,
)
from mtp_gateway.adapters.northbound.webui.schemas.services import (
    ProcedureInfo,
    ServiceCommand,
    ServiceCommandRequest,
    ServiceCommandResponse,
    ServiceListResponse,
    ServiceResponse,
    ServiceState,
)
from mtp_gateway.adapters.northbound.webui.security.rbac import Permission
from mtp_gateway.domain.state_machine.packml import PackMLCommand

if TYPE_CHECKING:
    from mtp_gateway.application.service_manager import ServiceManager

logger = structlog.get_logger(__name__)

router = APIRouter()


def _state_to_enum(state: object) -> ServiceState:
    """Convert PackML state to enum."""
    state_name = state.name if hasattr(state, "name") else str(state)
    try:
        return ServiceState(state_name)
    except ValueError:
        return ServiceState.UNDEFINED


def _format_service_response(
    service_name: str,
    service_manager: ServiceManager,
) -> ServiceResponse:
    """Format a service for API response."""
    # Get service state from manager
    state = service_manager.get_service_state(service_name)

    # Get procedures from config
    procedures: list[ProcedureInfo] = []
    service_config = service_manager.get_service_config(service_name)
    if service_config:
        for proc in service_config.procedures:
            procedures.append(
                ProcedureInfo(
                    id=proc.id,
                    name=proc.name,
                    is_default=proc.is_default,
                )
            )

    # Get interlock state
    interlocked = service_manager.is_service_interlocked(service_name)
    interlock_reason = None
    if interlocked:
        interlock_reason = "Interlock active"

    return ServiceResponse(
        name=service_name,
        state=_state_to_enum(state),
        state_time=None,  # Would need state tracking
        procedure_id=None,  # Would need procedure tracking
        procedure_name=None,
        procedures=procedures,
        interlocked=interlocked,
        interlock_reason=interlock_reason,
        mode=service_config.mode.value if service_config else "thin_proxy",
    )


@router.get(
    "",
    response_model=ServiceListResponse,
    dependencies=[Depends(require_permission(Permission.SERVICES_READ))],
)
async def list_services(
    current_user: CurrentUserDep,
    service_manager: ServiceManagerDep,
) -> ServiceListResponse:
    """List all services with current state.

    Requires: services:read permission

    Args:
        current_user: Authenticated user
        service_manager: Service manager instance

    Returns:
        List of all services with state
    """
    if service_manager is None:
        return ServiceListResponse(services=[], count=0)

    services: list[ServiceResponse] = []

    # Get all service names
    service_names = service_manager.get_all_service_names()

    for name in service_names:
        services.append(_format_service_response(name, service_manager))

    logger.debug(
        "Listed services",
        username=current_user.username,
        count=len(services),
    )

    return ServiceListResponse(
        services=services,
        count=len(services),
    )


@router.get(
    "/{service_name}",
    response_model=ServiceResponse,
    dependencies=[Depends(require_permission(Permission.SERVICES_READ))],
)
async def get_service(
    service_name: str,
    _current_user: CurrentUserDep,
    service_manager: ServiceManagerDep,
) -> ServiceResponse:
    """Get a single service state.

    Requires: services:read permission

    Args:
        service_name: Service name
        current_user: Authenticated user
        service_manager: Service manager instance

    Returns:
        Service state

    Raises:
        HTTPException: If service not found
    """
    if service_manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service manager not available",
        )

    state = service_manager.get_service_state(service_name)
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Service not found: {service_name}",
        )

    return _format_service_response(service_name, service_manager)


@router.post(
    "/{service_name}/command",
    response_model=ServiceCommandResponse,
    dependencies=[Depends(require_permission(Permission.SERVICES_COMMAND))],
)
async def send_command(
    service_name: str,
    request: ServiceCommandRequest,
    current_user: CurrentUserDep,
    service_manager: ServiceManagerDep,
) -> ServiceCommandResponse:
    """Send a command to a service.

    Requires: services:command permission

    Args:
        service_name: Service name
        request: Command to send
        current_user: Authenticated user
        service_manager: Service manager instance

    Returns:
        Command result

    Raises:
        HTTPException: If service not found or command fails
    """
    if service_manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service manager not available",
        )

    # Get current state
    current_state = service_manager.get_service_state(service_name)
    if current_state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Service not found: {service_name}",
        )

    previous_state = _state_to_enum(current_state)

    # Map API command to PackML command
    command_mapping = {
        ServiceCommand.START: "START",
        ServiceCommand.STOP: "STOP",
        ServiceCommand.HOLD: "HOLD",
        ServiceCommand.UNHOLD: "UNHOLD",
        ServiceCommand.SUSPEND: "SUSPEND",
        ServiceCommand.UNSUSPEND: "UNSUSPEND",
        ServiceCommand.ABORT: "ABORT",
        ServiceCommand.CLEAR: "CLEAR",
        ServiceCommand.RESET: "RESET",
    }

    packml_command = command_mapping.get(request.command)
    if not packml_command:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown command: {request.command}",
        )

    try:
        command_enum = PackMLCommand[packml_command]

        # Send command
        await service_manager.send_command(
            service_name,
            command_enum,
            procedure_id=request.procedure_id,
        )

        # Get new state
        new_state = service_manager.get_service_state(service_name)

        logger.info(
            "Service command sent",
            username=current_user.username,
            service=service_name,
            command=request.command.value,
            previous_state=previous_state.value,
            new_state=_state_to_enum(new_state).value if new_state else "unknown",
        )

        return ServiceCommandResponse(
            success=True,
            service_name=service_name,
            command=request.command,
            previous_state=previous_state,
            current_state=_state_to_enum(new_state) if new_state else previous_state,
            message=f"Command {request.command.value} accepted",
        )

    except ValueError as e:
        logger.warning(
            "Service command rejected",
            username=current_user.username,
            service=service_name,
            command=request.command.value,
            error=str(e),
        )
        return ServiceCommandResponse(
            success=False,
            service_name=service_name,
            command=request.command,
            previous_state=previous_state,
            current_state=previous_state,
            message=str(e),
        )

    except Exception as e:
        logger.exception(
            "Service command error",
            username=current_user.username,
            service=service_name,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Command failed: {e}",
        ) from e
