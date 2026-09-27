import re
import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, field_validator, model_validator


_EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserLoginRequest(BaseModel):
    username_or_email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


class SendVerificationCodeRequest(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        clean = v.strip().lower()
        if not _EMAIL_REGEX.match(clean):
            raise ValueError("Invalid email format")
        return clean


class VerifyCodeRequest(BaseModel):
    email: str
    code: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        clean = v.strip().lower()
        if not _EMAIL_REGEX.match(clean):
            raise ValueError("Invalid email format")
        return clean

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        clean = v.strip()
        if not (clean.isdigit() and len(clean) == 6):
            raise ValueError("Verification code must be exactly 6 digits")
        return clean


class VerificationTokenResponse(BaseModel):
    status: str = "verified"
    verification_token: str
    message: str


class CreateEnvironmentRequest(BaseModel):
    """Request to create a new organization + admin account."""
    organization_name: str
    admin_email: str
    admin_username: str
    admin_password: str
    confirm_password: Optional[str] = None
    admin_full_name: Optional[str] = None
    verification_code: Optional[str] = None
    verification_token: Optional[str] = None

    @field_validator("admin_email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        clean = v.strip().lower()
        if not _EMAIL_REGEX.match(clean):
            raise ValueError("Invalid email format")
        return clean

    @field_validator("admin_password")
    @classmethod
    def validate_password_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")
        return v

    @model_validator(mode="after")
    def validate_matching_passwords(self):
        if self.confirm_password is not None and self.admin_password != self.confirm_password:
            raise ValueError("Passwords do not match")
        return self


class CreateEnvironmentResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"
    organization: "OrganizationOut"


class ForgotPasswordRequest(BaseModel):
    """Request a password reset link/token for an email."""
    email: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        clean = v.strip().lower()
        if not _EMAIL_REGEX.match(clean):
            raise ValueError("Invalid email format")
        return clean


class ResetPasswordRequest(BaseModel):
    """Reset password using a valid reset token."""
    token: str
    new_password: str
    confirm_password: str

    @field_validator("new_password")
    @classmethod
    def validate_password_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")
        return v

    @model_validator(mode="after")
    def validate_matching_passwords(self):
        if self.new_password != self.confirm_password:
            raise ValueError("Passwords do not match")
        return self


# Forward references resolved at module level
from server.schemas.user import UserOut
from server.schemas.organization import OrganizationOut

TokenResponse.model_rebuild()
CreateEnvironmentResponse.model_rebuild()
