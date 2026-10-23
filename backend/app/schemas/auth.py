"""Request and response models for reader accounts."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, EmailStr, Field, model_validator

TERMS_VERSION = "2026-10"


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    display_name: str = Field(default="", max_length=80)
    remember: bool = False
    accept_terms: bool
    website: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def terms_required(self) -> "SignupRequest":
        if not self.accept_terms:
            raise ValueError("Accept the terms and privacy notice to continue.")
        return self


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    remember: bool = False


class TwoFactorLoginRequest(BaseModel):
    challenge_token: str = Field(min_length=16, max_length=200)
    code: str = Field(min_length=1, max_length=32)
    remember: Optional[bool] = None


class TwoFactorSetupRequest(BaseModel):
    password: str = Field(default="", max_length=128)


class TwoFactorEnableRequest(BaseModel):
    code: str = Field(min_length=1, max_length=32)


class TwoFactorDisableRequest(BaseModel):
    password: str = Field(default="", max_length=128)
    code: str = Field(default="", max_length=32)


class RecoveryCodesRequest(BaseModel):
    password: str = Field(default="", max_length=128)
    code: str = Field(min_length=1, max_length=32)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=16, max_length=200)
    password: str = Field(min_length=1, max_length=128)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(default="", max_length=128)
    new_password: str = Field(min_length=1, max_length=128)
    code: str = Field(default="", max_length=32)


class VerifyEmailRequest(BaseModel):
    token: str = Field(min_length=16, max_length=200)


class ProfileUpdateRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)


class DeleteAccountRequest(BaseModel):
    password: str = Field(default="", max_length=128)
    confirm_email: EmailStr
    code: str = Field(default="", max_length=32)


class GoogleUnlinkRequest(BaseModel):
    password: str = Field(default="", max_length=128)


class AuthUser(BaseModel):
    id: str
    email: str
    display_name: str
    email_verified: bool
    has_password: bool
    totp_enabled: bool
    google_linked: bool
    recovery_codes_remaining: int
    created_at: Optional[str] = None
    last_login_at: Optional[str] = None


class SessionInfo(BaseModel):
    id: str
    current: bool
    device: str
    ip: Optional[str] = None
    auth_method: str
    remember: bool
    created_at: str
    last_seen_at: str
    expires_at: str


class SecurityEvent(BaseModel):
    event: str
    ip: Optional[str] = None
    created_at: str
    metadata: Dict[str, Any] = {}


class AuthSessionResponse(BaseModel):
    user: AuthUser
    expires_at: str
    two_factor_required: bool = False


class MeResponse(BaseModel):
    user: Optional[AuthUser] = None
    expires_at: Optional[str] = None


class UserResponse(BaseModel):
    user: AuthUser
    message: str = "Saved."


class ActionResponse(BaseModel):
    status: str
    message: str


class TwoFactorChallengeResponse(BaseModel):
    two_factor_required: bool = True
    challenge_token: str
    expires_in: int
    email_masked: str


class AuthConfigResponse(BaseModel):
    google_enabled: bool
    email_delivery: str
    environment: str
    password_min_length: int
    terms_version: str


class AuthMessageResponse(BaseModel):
    status: str
    message: str
    dev_verification_link: Optional[str] = None
    dev_reset_link: Optional[str] = None


class EmailVerificationCheck(BaseModel):
    valid: bool
    email_masked: Optional[str] = None
    expired: bool = False


class SessionsResponse(BaseModel):
    sessions: List[SessionInfo]


class ActivityResponse(BaseModel):
    events: List[SecurityEvent]


class TotpSetupResponse(BaseModel):
    secret: str
    otpauth_uri: str
    qr_data_uri: Optional[str] = None
    expires_in: int


class TotpEnableResponse(BaseModel):
    user: AuthUser
    recovery_codes: List[str]


class RecoveryCodesResponse(BaseModel):
    recovery_codes: List[str]


class GoogleStartResponse(BaseModel):
    url: str
