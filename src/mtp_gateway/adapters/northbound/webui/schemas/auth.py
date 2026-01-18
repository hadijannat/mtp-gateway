"""Authentication schemas for WebUI API.

Provides request/response models for login, token refresh, and user info.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    """Login request body.

    Attributes:
        username: User's username
        password: User's password (plain text, will be verified against hash)
    """

    model_config = ConfigDict(extra="forbid")

    username: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Username",
    )
    password: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Password",
    )


class TokenResponse(BaseModel):
    """Token response with access and refresh tokens.

    Attributes:
        access_token: JWT access token for API authentication
        refresh_token: JWT refresh token for obtaining new access tokens
        token_type: Always "bearer"
        expires_in: Access token expiration time in seconds
    """

    model_config = ConfigDict(extra="forbid")

    access_token: str = Field(..., description="JWT access token")
    refresh_token: str = Field(..., description="JWT refresh token")
    token_type: str = Field(default="bearer", description="Token type")
    expires_in: int = Field(..., ge=0, description="Token expiration in seconds")


class LoginResponse(BaseModel):
    """Login response with tokens and user info.

    Attributes:
        tokens: Access and refresh tokens
        user: Current user information
    """

    model_config = ConfigDict(extra="forbid")

    tokens: TokenResponse
    user: UserResponse


class RefreshRequest(BaseModel):
    """Token refresh request.

    Attributes:
        refresh_token: Valid refresh token to exchange for new access token
    """

    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(..., description="Refresh token")


class UserResponse(BaseModel):
    """User information response.

    Attributes:
        id: User database ID
        username: Unique username
        email: User email address
        role: User's role name
        permissions: List of granted permissions
        is_active: Whether user account is active
    """

    model_config = ConfigDict(extra="forbid")

    id: int = Field(..., description="User ID")
    username: str = Field(..., description="Username")
    email: str = Field(..., description="Email address")
    role: str = Field(..., description="Role name")
    permissions: list[str] = Field(default_factory=list, description="Granted permissions")
    is_active: bool = Field(default=True, description="Account active status")


# Update forward reference
LoginResponse.model_rebuild()
