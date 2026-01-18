#!/usr/bin/env python3
"""Mock FastAPI server for WebUI screenshot capture.

Provides demo data for the "Reactor Temperature Control" scenario
without requiring full gateway setup.
"""

from datetime import datetime, timedelta, timezone
import jwt
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Mock MTP Gateway WebUI")

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# JWT config
JWT_SECRET = "demo-secret-for-screenshots"
JWT_ALGORITHM = "HS256"

# Demo users
DEMO_USERS = {
    "operator": {"password": "operator123", "role": "operator", "id": 1},
    "engineer": {"password": "engineer123", "role": "engineer", "id": 2},
    "admin": {"password": "admin123", "role": "admin", "id": 3},
}


# Pydantic models
class LoginRequest(BaseModel):
    username: str
    password: str


def create_token(username: str, user_id: int, role: str) -> str:
    """Create a JWT token."""
    expires = datetime.now(timezone.utc) + timedelta(hours=24)
    payload = {
        "sub": username,
        "user_id": user_id,
        "role": role,
        "exp": expires,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_token(auth_header: str | None) -> dict:
    """Verify JWT token from Authorization header."""
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = auth_header[7:]
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


# Demo data timestamp
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# Auth endpoints
@app.post("/api/v1/auth/login")
async def login(request: LoginRequest):
    """Authenticate user and return tokens."""
    user = DEMO_USERS.get(request.username)
    if not user or user["password"] != request.password:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    access_token = create_token(request.username, user["id"], user["role"])
    refresh_token = create_token(request.username, user["id"], user["role"])

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": 86400,
        "user": {
            "id": user["id"],
            "username": request.username,
            "email": f"{request.username}@example.com",
            "role": user["role"],
            "is_active": True,
            "permissions": ["read:tags", "write:tags", "read:services", "write:services"],
        },
    }


@app.get("/api/v1/auth/me")
async def get_me(authorization: str | None = Header(None)):
    """Get current user info."""
    payload = verify_token(authorization)
    return {
        "id": payload["user_id"],
        "username": payload["sub"],
        "email": f"{payload['sub']}@example.com",
        "role": payload["role"],
        "is_active": True,
        "permissions": ["read:tags", "write:tags", "read:services", "write:services"],
    }


# Health endpoint
@app.get("/api/v1/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "version": "1.0.0",
        "uptime_seconds": 3661,
        "timestamp": now_iso(),
    }


# Tags endpoint - Reactor Temperature Control demo data
@app.get("/api/v1/tags")
async def get_tags(authorization: str | None = Header(None)):
    """Get all tags with demo reactor data."""
    verify_token(authorization)

    tags = [
        # Analog values - Reactor scenario
        {
            "name": "reactor_temp",
            "value": 78.5,
            "quality": "good",
            "timestamp": now_iso(),
            "unit": "°C",
            "description": "Reactor Temperature",
        },
        {
            "name": "jacket_temp",
            "value": 65.2,
            "quality": "good",
            "timestamp": now_iso(),
            "unit": "°C",
            "description": "Jacket Temperature",
        },
        {
            "name": "reactor_pressure",
            "value": 2.35,
            "quality": "good",
            "timestamp": now_iso(),
            "unit": "bar",
            "description": "Reactor Pressure",
        },
        {
            "name": "flow_rate",
            "value": 125.8,
            "quality": "good",
            "timestamp": now_iso(),
            "unit": "L/min",
            "description": "Flow Rate",
        },
        {
            "name": "level_pct",
            "value": 67.3,
            "quality": "good",
            "timestamp": now_iso(),
            "unit": "%",
            "description": "Tank Level",
        },
        {
            "name": "ph_value",
            "value": 7.2,
            "quality": "good",
            "timestamp": now_iso(),
            "unit": "pH",
            "description": "pH Value",
        },
        # Digital values
        {
            "name": "inlet_valve_open",
            "value": True,
            "quality": "good",
            "timestamp": now_iso(),
            "description": "Inlet Valve Status",
        },
        {
            "name": "outlet_valve_open",
            "value": False,
            "quality": "good",
            "timestamp": now_iso(),
            "description": "Outlet Valve Status",
        },
        {
            "name": "agitator_running",
            "value": True,
            "quality": "good",
            "timestamp": now_iso(),
            "description": "Agitator Motor Running",
        },
        {
            "name": "cooling_active",
            "value": False,
            "quality": "good",
            "timestamp": now_iso(),
            "description": "Cooling System Active",
        },
    ]

    return {"tags": tags, "count": len(tags)}


# Services endpoint - Demo services
@app.get("/api/v1/services")
async def get_services(authorization: str | None = Header(None)):
    """Get all services with demo data."""
    verify_token(authorization)

    services = [
        {
            "name": "Dosing",
            "state": "EXECUTE",
            "state_time": now_iso(),
            "procedure_id": 1,
            "procedure_name": "StandardDose",
            "procedures": [
                {"id": 1, "name": "StandardDose", "is_default": True},
                {"id": 2, "name": "HighVolumeDose", "is_default": False},
            ],
            "interlocked": False,
            "mode": "THICK_PROXY",
        },
        {
            "name": "Mixing",
            "state": "IDLE",
            "state_time": now_iso(),
            "procedure_id": None,
            "procedure_name": None,
            "procedures": [
                {"id": 1, "name": "StandardMix", "is_default": True},
                {"id": 2, "name": "GentleMix", "is_default": False},
            ],
            "interlocked": True,
            "interlock_reason": "High temperature alarm active",
            "mode": "THICK_PROXY",
        },
        {
            "name": "Heating",
            "state": "STOPPED",
            "state_time": now_iso(),
            "procedure_id": None,
            "procedure_name": None,
            "procedures": [
                {"id": 1, "name": "RampUp", "is_default": True},
            ],
            "interlocked": False,
            "mode": "THIN_PROXY",
        },
        {
            "name": "Transfer",
            "state": "IDLE",
            "state_time": now_iso(),
            "procedure_id": None,
            "procedure_name": None,
            "procedures": [
                {"id": 1, "name": "ToStorage", "is_default": True},
                {"id": 2, "name": "ToPackaging", "is_default": False},
            ],
            "interlocked": False,
            "mode": "THICK_PROXY",
        },
    ]

    return {"services": services, "count": len(services)}


@app.get("/api/v1/services/{name}")
async def get_service(name: str, authorization: str | None = Header(None)):
    """Get a specific service."""
    verify_token(authorization)
    services_response = await get_services(authorization)
    for svc in services_response["services"]:
        if svc["name"] == name:
            return svc
    raise HTTPException(status_code=404, detail=f"Service '{name}' not found")


# Alarms endpoint - Demo alarms
@app.get("/api/v1/alarms")
async def get_alarms(authorization: str | None = Header(None)):
    """Get all alarms with demo data."""
    verify_token(authorization)

    now = datetime.now(timezone.utc)

    alarms = [
        {
            "id": 1,
            "alarm_id": "HH_REACTOR_TEMP",
            "source": "ReactorTempMon",
            "priority": 1,  # Critical
            "state": "active",
            "message": "Reactor temperature HIGH-HIGH (>85°C)",
            "value": 87.2,
            "raised_at": (now - timedelta(minutes=5)).isoformat(),
        },
        {
            "id": 2,
            "alarm_id": "H_PRESSURE",
            "source": "PressureMon",
            "priority": 2,  # High
            "state": "active",
            "message": "Reactor pressure HIGH warning (>2.5 bar)",
            "value": 2.65,
            "raised_at": (now - timedelta(minutes=12)).isoformat(),
        },
        {
            "id": 3,
            "alarm_id": "L_LEVEL",
            "source": "LevelMon",
            "priority": 3,  # Medium
            "state": "acknowledged",
            "message": "Tank level LOW warning (<30%)",
            "value": 28.5,
            "raised_at": (now - timedelta(minutes=30)).isoformat(),
            "acknowledged_at": (now - timedelta(minutes=25)).isoformat(),
            "acknowledged_by": "operator",
        },
        {
            "id": 4,
            "alarm_id": "FLOW_DEVIATION",
            "source": "FlowMon",
            "priority": 4,  # Low
            "state": "cleared",
            "message": "Flow rate deviation detected",
            "value": 118.0,
            "raised_at": (now - timedelta(hours=2)).isoformat(),
            "cleared_at": (now - timedelta(hours=1, minutes=45)).isoformat(),
        },
    ]

    active_count = sum(1 for a in alarms if a["state"] == "active")
    unack_count = sum(1 for a in alarms if a["state"] == "active")

    return {
        "alarms": alarms,
        "count": len(alarms),
        "active_count": active_count,
        "unacknowledged_count": unack_count,
    }


# History endpoint - Demo trend data
@app.get("/api/v1/history/{tag_name}")
async def get_history(
    tag_name: str,
    hours: int = 24,
    authorization: str | None = Header(None),
):
    """Get historical data for a tag."""
    verify_token(authorization)

    import random

    now = datetime.now(timezone.utc)
    points = []

    # Base values by tag
    base_values = {
        "reactor_temp": 75.0,
        "jacket_temp": 62.0,
        "reactor_pressure": 2.2,
        "flow_rate": 120.0,
        "level_pct": 65.0,
    }

    base = base_values.get(tag_name, 50.0)

    # Generate hourly data points
    for i in range(hours, -1, -1):
        t = now - timedelta(hours=i)
        # Add some variation
        variation = random.uniform(-5, 8)
        value = base + variation
        points.append({
            "time": t.isoformat(),
            "value": round(value, 2),
            "quality": "good",
        })

    return {
        "tag_name": tag_name,
        "points": points,
        "count": len(points),
        "start_time": points[0]["time"] if points else now.isoformat(),
        "end_time": points[-1]["time"] if points else now.isoformat(),
    }


@app.get("/api/v1/history")
async def get_multi_history(
    tags: str = "reactor_temp,jacket_temp",
    hours: int = 24,
    authorization: str | None = Header(None),
):
    """Get historical data for multiple tags."""
    verify_token(authorization)

    import random

    now = datetime.now(timezone.utc)
    tag_names = [t.strip() for t in tags.split(",")]

    base_values = {
        "reactor_temp": 75.0,
        "jacket_temp": 62.0,
        "reactor_pressure": 2.2,
        "flow_rate": 120.0,
        "level_pct": 65.0,
    }

    result = {}

    for tag_name in tag_names:
        points = []
        base = base_values.get(tag_name, 50.0)

        for i in range(hours, -1, -1):
            t = now - timedelta(hours=i)
            variation = random.uniform(-5, 8)
            value = base + variation
            points.append({
                "time": t.isoformat(),
                "value": round(value, 2),
                "quality": "good",
            })
        result[tag_name] = points

    return {
        "tags": result,
        "count": len(tag_names),
        "start_time": (now - timedelta(hours=hours)).isoformat(),
        "end_time": now.isoformat(),
    }


@app.get("/api/v1/history/available-tags")
async def get_available_tags(authorization: str | None = Header(None)):
    """Get list of tags with history."""
    verify_token(authorization)

    tags = [
        "reactor_temp",
        "jacket_temp",
        "reactor_pressure",
        "flow_rate",
        "level_pct",
    ]

    return {"tags": tags, "count": len(tags)}


if __name__ == "__main__":
    import uvicorn
    print("Starting mock WebUI server on http://localhost:8080")
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="warning")
