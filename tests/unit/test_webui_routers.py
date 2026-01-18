from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from mtp_gateway.adapters.northbound.webui import dependencies
from mtp_gateway.adapters.northbound.webui.routers import (
    alarms as alarms_router,
)
from mtp_gateway.adapters.northbound.webui.routers import (
    auth as auth_router,
)
from mtp_gateway.adapters.northbound.webui.routers import (
    health as health_router,
)
from mtp_gateway.adapters.northbound.webui.routers import (
    history as history_router,
)
from mtp_gateway.adapters.northbound.webui.routers import (
    services as services_router,
)
from mtp_gateway.adapters.northbound.webui.routers import (
    tags as tags_router,
)
from mtp_gateway.adapters.northbound.webui.security.jwt import TokenService
from mtp_gateway.adapters.northbound.webui.security.rbac import Permission, User
from mtp_gateway.config.schema import ProcedureConfig, ProxyMode, ServiceConfig
from mtp_gateway.domain.model.tags import DataType, TagDefinition, TagState, TagValue
from mtp_gateway.domain.state_machine.packml import PackMLState


class StubTagManager:
    def __init__(self) -> None:
        self._tags: dict[str, TagState] = {}

    def add_tag(self, name: str, value: float, *, writable: bool = False) -> None:
        tag_def = TagDefinition(
            name=name,
            connector="dummy",
            address="40001",
            datatype=DataType.FLOAT32,
            writable=writable,
            unit="degC",
        )
        state = TagState(definition=tag_def)
        state.update(TagValue.good(value))
        self._tags[name] = state

    def get_all_tag_names(self) -> list[str]:
        return sorted(self._tags.keys())

    def get_tag(self, name: str) -> TagState | None:
        return self._tags.get(name)

    def get_value(self, name: str) -> TagValue | None:
        state = self._tags.get(name)
        return state.current_value if state else None

    async def write_tag(self, name: str, value: Any) -> None:
        state = self._tags.get(name)
        if not state:
            raise ValueError("Tag not found")
        state.update(TagValue.good(value))


class StubServiceManager:
    def __init__(self) -> None:
        self._states: dict[str, PackMLState] = {"Dosing": PackMLState.IDLE}
        self._config = ServiceConfig(
            name="Dosing",
            mode=ProxyMode.THIN,
            procedures=[
                ProcedureConfig(
                    id=1,
                    name="Default",
                    is_default=True,
                )
            ],
        )
        self.last_command: str | None = None

    def get_all_service_names(self) -> list[str]:
        return sorted(self._states.keys())

    def get_service_state(self, name: str) -> PackMLState | None:
        return self._states.get(name)

    def get_service_config(self, name: str) -> ServiceConfig | None:
        return self._config if name in self._states else None

    def is_service_interlocked(self, _name: str) -> bool:
        return False

    async def send_command(self, name: str, command: Any, procedure_id: int | None = None) -> None:
        if name not in self._states:
            raise ValueError("Service not found")
        self.last_command = command.name if hasattr(command, "name") else str(command)
        _ = procedure_id
        self._states[name] = PackMLState.EXECUTE


@pytest.fixture(autouse=True)
def reset_mock_alarms() -> None:
    original = deepcopy(alarms_router._MOCK_ALARMS)
    yield
    alarms_router._MOCK_ALARMS = deepcopy(original)


@pytest.fixture()
def webui_client() -> TestClient:
    app = FastAPI()

    tag_manager = StubTagManager()
    tag_manager.add_tag("temp_pv", 20.5, writable=True)

    service_manager = StubServiceManager()
    token_service = TokenService(secret="x" * 32)

    app.state.tag_manager = tag_manager
    app.state.service_manager = service_manager
    app.state.token_service = token_service
    app.state.db_pool = None

    app.include_router(tags_router.router, prefix="/tags")
    app.include_router(services_router.router, prefix="/services")
    app.include_router(alarms_router.router, prefix="/alarms")
    app.include_router(history_router.router, prefix="/history")
    app.include_router(auth_router.router, prefix="/auth")
    app.include_router(health_router.router, prefix="/health")

    def override_current_user() -> User:
        return User(
            id=1,
            username="admin",
            email="admin@localhost",
            role="admin",
            permissions=[perm.value for perm in Permission],
            is_active=True,
        )

    def override_tag_manager(_: Request) -> StubTagManager:
        return tag_manager

    def override_service_manager(_: Request) -> StubServiceManager:
        return service_manager

    def override_token_service(_: Request) -> TokenService:
        return token_service

    app.dependency_overrides[dependencies.get_current_user] = override_current_user
    app.dependency_overrides[dependencies.get_tag_manager] = override_tag_manager
    app.dependency_overrides[dependencies.get_service_manager] = override_service_manager
    app.dependency_overrides[dependencies.get_token_service] = override_token_service

    return TestClient(app)


def test_health_check(webui_client: TestClient) -> None:
    response = webui_client.get("/health/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "healthy"


def test_list_tags(webui_client: TestClient) -> None:
    response = webui_client.get("/tags")
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["tags"][0]["name"] == "temp_pv"


def test_get_tag(webui_client: TestClient) -> None:
    response = webui_client.get("/tags/temp_pv")
    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "temp_pv"
    assert payload["value"] == 20.5


def test_write_tag(webui_client: TestClient) -> None:
    response = webui_client.post("/tags/temp_pv", json={"value": 33.3})
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["new_value"] == 33.3


def test_list_services(webui_client: TestClient) -> None:
    response = webui_client.get("/services")
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["services"][0]["name"] == "Dosing"


def test_send_service_command(webui_client: TestClient) -> None:
    response = webui_client.post("/services/Dosing/command", json={"command": "START"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["command"] == "START"


def test_history_without_db_returns_empty(webui_client: TestClient) -> None:
    response = webui_client.get(
        "/history/tags",
        params={
            "tag": "temp_pv",
            "start": "2024-01-01T00:00:00Z",
            "end": "2024-01-01T01:00:00Z",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 0


def test_list_alarms_mock_mode(webui_client: TestClient) -> None:
    response = webui_client.get("/alarms")
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 2


def test_ack_and_clear_alarm_mock_mode(webui_client: TestClient) -> None:
    ack_response = webui_client.post("/alarms/1/acknowledge", json={"comment": "ok"})
    assert ack_response.status_code == 200
    ack_payload = ack_response.json()
    assert ack_payload["success"] is True

    clear_response = webui_client.post("/alarms/1/clear")
    assert clear_response.status_code == 200
    clear_payload = clear_response.json()
    assert clear_payload["state"] == "cleared"


@pytest.mark.filterwarnings("ignore:datetime\\.datetime\\.utcnow\\(\\) is deprecated")
def test_auth_login_and_refresh(webui_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_router, "verify_password", lambda *_args, **_kwargs: True)
    login_response = webui_client.post(
        "/auth/login",
        json={"username": "admin", "password": "admin"},
    )
    assert login_response.status_code == 200
    login_payload = login_response.json()
    refresh_token = login_payload["tokens"]["refresh_token"]

    refresh_response = webui_client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert refresh_response.status_code == 200
    refresh_payload = refresh_response.json()
    assert refresh_payload["access_token"]
