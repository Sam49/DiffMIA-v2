from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.models.enums import UserRole
from app.schemas.common import ORMModel


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=128)
    email: str = Field(default="", max_length=255, pattern=r"^[^@\s]*@[^@\s]*$")
    role: UserRole = UserRole.VIEWER

    @field_validator("role")
    @classmethod
    def _no_privileged_admin_creation(cls, value: UserRole) -> UserRole:
        if value is UserRole.ADMIN:
            raise ValueError("ADMIN accounts cannot be created through the API.")
        return value


class RegisterRequest(BaseModel):
    """Self-service sign-up (POST /auth/register, no authentication)."""

    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=128)
    email: str = Field(min_length=3, max_length=255, pattern=r"^[^@\s]*@[^@\s]*$")


class VerificationInfo(BaseModel):
    """Attached to register/resend responses when email delivery is simulated."""

    required: bool
    development_token: str | None = None


class ForgotPasswordRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=10, max_length=512)
    new_password: str = Field(min_length=8, max_length=128)


class VerifyEmailRequest(BaseModel):
    token: str = Field(min_length=10, max_length=512)


class RegistrationStatus(BaseModel):
    registration_enabled: bool


class UserUpdate(BaseModel):
    password: str | None = Field(default=None, min_length=6, max_length=128)
    email: str | None = Field(default=None, max_length=255)
    role: UserRole | None = None
    is_active: bool | None = None


class UserOut(ORMModel):
    id: int
    username: str
    email: str
    role: UserRole
    is_active: bool
    auth_provider: str = "local"
    email_verified: bool = True
    #: True when a Google identity is attached (Settings → Connected accounts).
    google_linked: bool = False
    created_at: object | None = None


class GoogleLinkStartOut(BaseModel):
    """The Google consent URL the browser must be sent to in order to link."""

    authorize_url: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
    verification: VerificationInfo | None = None


class PasswordChange(BaseModel):
    old_password: str
    new_password: str = Field(min_length=6, max_length=128)


class OAuthStatus(BaseModel):
    google_enabled: bool
    self_registration: bool = False
    email_verification_required: bool = False

