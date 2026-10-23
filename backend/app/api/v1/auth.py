"""Reader account endpoints: credentials, sessions, 2FA and Google OIDC."""

from __future__ import annotations

import hmac
from typing import Any, Optional, Union
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import RedirectResponse

from app.auth import google as google_service
from app.auth import service as auth_service
from app.auth.errors import AuthError
from app.auth.security import (
    CSRF_COOKIE,
    OAUTH_STATE_COOKIE,
    SESSION_COOKIE,
    csrf_token_valid,
    iso_ts,
    issue_csrf_token,
    mask_email,
    now_ts,
)
from app.config import settings
from app.middleware.rate_limit import limiter
from app.schemas.auth import (
    ActionResponse,
    ActivityResponse,
    AuthConfigResponse,
    AuthMessageResponse,
    AuthSessionResponse,
    ChangePasswordRequest,
    DeleteAccountRequest,
    EmailVerificationCheck,
    ForgotPasswordRequest,
    GoogleStartResponse,
    GoogleUnlinkRequest,
    LoginRequest,
    MeResponse,
    ProfileUpdateRequest,
    RecoveryCodesRequest,
    RecoveryCodesResponse,
    ResetPasswordRequest,
    SessionsResponse,
    SignupRequest,
    TotpEnableResponse,
    TotpSetupResponse,
    TwoFactorChallengeResponse,
    TwoFactorDisableRequest,
    TwoFactorEnableRequest,
    TwoFactorLoginRequest,
    TwoFactorSetupRequest,
    UserResponse,
    VerifyEmailRequest,
)

router = APIRouter(prefix="/auth")


def _client_ip(request: Request) -> Optional[str]:
    return request.client.host if request.client else None


def _user_agent(request: Request) -> Optional[str]:
    return request.headers.get("user-agent")


def _same_site() -> str:
    value = (settings.auth_cookie_samesite or "lax").lower()
    return value if value in {"lax", "strict", "none"} else "lax"


def _cookie_security() -> dict[str, Any]:
    samesite = _same_site()
    return {
        "secure": bool(settings.secure_cookies or samesite == "none"),
        "samesite": samesite,
        "domain": settings.auth_cookie_domain or None,
    }


def _set_session_cookie(response: Response, token: str, expires_at: int) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=max(60, expires_at - now_ts()),
        path="/",
        httponly=True,
        **_cookie_security(),
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE,
        path="/",
        httponly=True,
        **_cookie_security(),
    )


def _set_csrf_cookie(response: Response) -> str:
    token = issue_csrf_token()
    response.set_cookie(
        key=CSRF_COOKIE,
        value=token,
        max_age=60 * 60 * 24 * 30,
        path="/",
        httponly=False,
        **_cookie_security(),
    )
    return token


def _ensure_csrf_cookie(request: Request, response: Response) -> str:
    existing = request.cookies.get(CSRF_COOKIE)
    if existing and csrf_token_valid(existing):
        return existing
    return _set_csrf_cookie(response)


def _set_oauth_state_cookie(response: Response, state: str) -> None:
    response.set_cookie(
        key=OAUTH_STATE_COOKIE,
        value=state,
        max_age=600,
        path="/v1/auth",
        httponly=True,
        secure=bool(settings.secure_cookies),
        samesite="lax",
        domain=settings.auth_cookie_domain or None,
    )


def _clear_oauth_state_cookie(response: Response) -> None:
    response.delete_cookie(
        key=OAUTH_STATE_COOKIE,
        path="/v1/auth",
        httponly=True,
        secure=bool(settings.secure_cookies),
        samesite="lax",
        domain=settings.auth_cookie_domain or None,
    )


def _origin(value: str) -> str:
    parts = urlsplit(value)
    return f"{parts.scheme}://{parts.netloc}".lower()


def _allowed_origins(request: Request) -> set[str]:
    values = list(settings.allowed_origins or [])
    for extra in (settings.app_base_url, settings.public_base_url, str(request.base_url)):
        if extra:
            values.append(extra)
    return {_origin(item) for item in values if item}


def require_csrf(request: Request) -> None:
    cookie = request.cookies.get(CSRF_COOKIE)
    header = request.headers.get("x-csrf-token")
    if (
        not cookie
        or not header
        or not hmac.compare_digest(cookie, header)
        or not csrf_token_valid(cookie)
    ):
        raise AuthError(403, "csrf_failed", "Your session token expired. Refresh the page and try again.")
    origin = request.headers.get("origin")
    if origin:
        if _origin(origin) not in _allowed_origins(request):
            raise AuthError(403, "origin_rejected", "This request came from an unapproved origin.")
    elif request.headers.get("sec-fetch-site", "").lower() == "cross-site":
        raise AuthError(403, "origin_rejected", "Cross-site requests are not allowed.")


def require_user(request: Request) -> auth_service.SessionContext:
    session = auth_service.get_session_context(request.cookies.get(SESSION_COOKIE))
    if not session:
        raise AuthError(401, "not_authenticated", "Sign in to continue.")
    return session


def _app_base(request: Request) -> str:
    if settings.app_base_url:
        return settings.app_base_url.rstrip("/")
    if settings.environment != "production":
        return "http://localhost:5173"
    return str(request.base_url).rstrip("/")


def _login_error_redirect(
    request: Request, code: str, clear_state: bool = False
) -> RedirectResponse:
    response = RedirectResponse(
        f"{_app_base(request)}/login?{urlencode({'error': code})}", status_code=302
    )
    if clear_state:
        _clear_oauth_state_cookie(response)
    return response


@router.get("/config", response_model=AuthConfigResponse)
@limiter.limit("60/minute")
def auth_config(request: Request) -> AuthConfigResponse:
    return AuthConfigResponse(**auth_service.config_dict())


@router.get("/csrf")
@limiter.limit("60/minute")
def csrf(request: Request, response: Response) -> dict[str, str]:
    return {"token": _set_csrf_cookie(response)}


@router.post(
    "/signup",
    response_model=AuthMessageResponse,
    status_code=201,
    dependencies=[Depends(require_csrf)],
)
@limiter.limit("6/hour")
def signup(request: Request, payload: SignupRequest) -> AuthMessageResponse:
    result = auth_service.sign_up(
        email=str(payload.email),
        password=payload.password,
        display_name=payload.display_name,
        accept_terms=payload.accept_terms,
        honeypot=payload.website,
        ip=_client_ip(request),
        user_agent=_user_agent(request),
    )
    return AuthMessageResponse(**result)


@router.post(
    "/login",
    response_model=Union[AuthSessionResponse, TwoFactorChallengeResponse],
    dependencies=[Depends(require_csrf)],
)
@limiter.limit("20/minute")
def login(
    request: Request, response: Response, payload: LoginRequest
) -> Union[AuthSessionResponse, TwoFactorChallengeResponse]:
    result = auth_service.log_in(
        email=str(payload.email),
        password=payload.password,
        remember=payload.remember,
        ip=_client_ip(request),
        user_agent=_user_agent(request),
    )
    _set_csrf_cookie(response)
    if result.two_factor_required and result.challenge_token:
        return TwoFactorChallengeResponse(
            challenge_token=result.challenge_token,
            expires_in=auth_service.CHALLENGE_TTL_SECONDS,
            email_masked=mask_email(str(payload.email)),
        )
    if not result.user or not result.token or not result.expires_at:
        raise AuthError(500, "login_failed", "Could not complete sign-in. Try again.")
    _set_session_cookie(response, result.token, result.expires_at)
    return AuthSessionResponse(
        user=result.user,
        expires_at=iso_ts(result.expires_at) or "",
    )


@router.post(
    "/login/2fa",
    response_model=AuthSessionResponse,
    dependencies=[Depends(require_csrf)],
)
@limiter.limit("20/minute")
def login_two_factor(
    request: Request, response: Response, payload: TwoFactorLoginRequest
) -> AuthSessionResponse:
    result = auth_service.complete_two_factor(
        challenge_token=payload.challenge_token,
        code=payload.code,
        remember=payload.remember,
        ip=_client_ip(request),
        user_agent=_user_agent(request),
    )
    if not result.user or not result.token or not result.expires_at:
        raise AuthError(500, "login_failed", "Could not complete sign-in. Try again.")
    _set_session_cookie(response, result.token, result.expires_at)
    _set_csrf_cookie(response)
    return AuthSessionResponse(
        user=result.user,
        expires_at=iso_ts(result.expires_at) or "",
    )


@router.post("/logout", response_model=ActionResponse, dependencies=[Depends(require_csrf)])
@limiter.limit("30/minute")
def logout(request: Request, response: Response) -> ActionResponse:
    auth_service.log_out(
        request.cookies.get(SESSION_COOKIE), _client_ip(request), _user_agent(request)
    )
    _clear_session_cookie(response)
    _set_csrf_cookie(response)
    return ActionResponse(status="signed_out", message="Signed out.")


@router.get("/me", response_model=MeResponse)
@limiter.limit("120/minute")
def me(request: Request, response: Response) -> MeResponse:
    _ensure_csrf_cookie(request, response)
    session = auth_service.get_session_context(request.cookies.get(SESSION_COOKIE))
    if not session:
        return MeResponse()
    return MeResponse(
        user=auth_service.serialize_user(session.user),
        expires_at=iso_ts(session.expires_at),
    )


@router.post(
    "/email/verify",
    response_model=AuthSessionResponse,
    dependencies=[Depends(require_csrf)],
)
@limiter.limit("20/minute")
def verify_email(
    request: Request, response: Response, payload: VerifyEmailRequest
) -> AuthSessionResponse:
    result = auth_service.verify_email(
        payload.token, _client_ip(request), _user_agent(request)
    )
    _set_session_cookie(response, result["token"], result["expires_ts"])
    _set_csrf_cookie(response)
    return AuthSessionResponse(
        user=result["user"], expires_at=result["expires_at"]
    )


@router.get("/email/verify/check", response_model=EmailVerificationCheck)
@limiter.limit("30/minute")
def check_email_verification(request: Request, token: str = Query(..., min_length=16, max_length=200)) -> EmailVerificationCheck:
    return EmailVerificationCheck(**auth_service.check_verification_token(token))


@router.post(
    "/email/resend",
    response_model=AuthMessageResponse,
    dependencies=[Depends(require_csrf)],
)
@limiter.limit("4/minute")
def resend_verification(
    request: Request,
    session: auth_service.SessionContext = Depends(require_user),
) -> AuthMessageResponse:
    result = auth_service.resend_verification(session.user["user_id"])
    return AuthMessageResponse(**result)


@router.post(
    "/password/forgot",
    response_model=AuthMessageResponse,
    dependencies=[Depends(require_csrf)],
)
@limiter.limit("5/minute")
def forgot_password(request: Request, payload: ForgotPasswordRequest) -> AuthMessageResponse:
    result = auth_service.request_password_reset(
        str(payload.email), _client_ip(request), _user_agent(request)
    )
    return AuthMessageResponse(**result)


@router.get("/password/reset/check", response_model=EmailVerificationCheck)
@limiter.limit("30/minute")
def check_password_reset(request: Request, token: str = Query(..., min_length=16, max_length=200)) -> EmailVerificationCheck:
    return EmailVerificationCheck(**auth_service.check_reset_token(token))


@router.post(
    "/password/reset",
    response_model=ActionResponse,
    dependencies=[Depends(require_csrf)],
)
@limiter.limit("10/minute")
def reset_password(
    request: Request, response: Response, payload: ResetPasswordRequest
) -> ActionResponse:
    result = auth_service.reset_password(
        payload.token, payload.password, _client_ip(request), _user_agent(request)
    )
    _clear_session_cookie(response)
    _set_csrf_cookie(response)
    return ActionResponse(**result)


@router.post(
    "/password/change",
    response_model=UserResponse,
    dependencies=[Depends(require_csrf)],
)
@limiter.limit("10/minute")
def change_password(
    request: Request,
    payload: ChangePasswordRequest,
    session: auth_service.SessionContext = Depends(require_user),
) -> UserResponse:
    result = auth_service.change_password(
        user_id=session.user["user_id"],
        session_id=session.session_id,
        current_password=payload.current_password,
        new_password=payload.new_password,
        code=payload.code,
        ip=_client_ip(request),
        user_agent=_user_agent(request),
    )
    return UserResponse(**result)


@router.post(
    "/profile",
    response_model=UserResponse,
    dependencies=[Depends(require_csrf)],
)
@limiter.limit("20/minute")
def update_profile(
    request: Request,
    payload: ProfileUpdateRequest,
    session: auth_service.SessionContext = Depends(require_user),
) -> UserResponse:
    result = auth_service.update_profile(
        session.user["user_id"],
        payload.display_name,
        _client_ip(request),
        _user_agent(request),
    )
    return UserResponse(**result)


@router.get("/sessions", response_model=SessionsResponse)
@limiter.limit("60/minute")
def list_sessions(
    request: Request,
    session: auth_service.SessionContext = Depends(require_user),
) -> SessionsResponse:
    return SessionsResponse(
        sessions=auth_service.list_sessions(session.user["user_id"], session.session_id)
    )


@router.post(
    "/sessions/{session_id}/revoke",
    response_model=ActionResponse,
    dependencies=[Depends(require_csrf)],
)
@limiter.limit("30/minute")
def revoke_session(
    request: Request,
    session_id: str,
    session: auth_service.SessionContext = Depends(require_user),
) -> ActionResponse:
    result = auth_service.revoke_session(
        session.user["user_id"],
        session_id,
        session.session_id,
        _client_ip(request),
        _user_agent(request),
    )
    return ActionResponse(**result)


@router.post(
    "/sessions/revoke-others",
    response_model=ActionResponse,
    dependencies=[Depends(require_csrf)],
)
@limiter.limit("10/minute")
def revoke_other_sessions(
    request: Request,
    session: auth_service.SessionContext = Depends(require_user),
) -> ActionResponse:
    result = auth_service.revoke_other_sessions(
        session.user["user_id"],
        session.session_id,
        _client_ip(request),
        _user_agent(request),
    )
    return ActionResponse(**result)


@router.get("/activity", response_model=ActivityResponse)
@limiter.limit("30/minute")
def activity(
    request: Request,
    session: auth_service.SessionContext = Depends(require_user),
) -> ActivityResponse:
    return ActivityResponse(events=auth_service.list_events(session.user["user_id"]))


@router.post(
    "/2fa/setup",
    response_model=TotpSetupResponse,
    dependencies=[Depends(require_csrf)],
)
@limiter.limit("10/minute")
def setup_two_factor(
    request: Request,
    payload: TwoFactorSetupRequest,
    session: auth_service.SessionContext = Depends(require_user),
) -> TotpSetupResponse:
    result = auth_service.setup_two_factor(
        user_id=session.user["user_id"],
        password=payload.password,
        ip=_client_ip(request),
        user_agent=_user_agent(request),
    )
    return TotpSetupResponse(**result)


@router.post(
    "/2fa/enable",
    response_model=TotpEnableResponse,
    dependencies=[Depends(require_csrf)],
)
@limiter.limit("10/minute")
def enable_two_factor(
    request: Request,
    payload: TwoFactorEnableRequest,
    session: auth_service.SessionContext = Depends(require_user),
) -> TotpEnableResponse:
    result = auth_service.enable_two_factor(
        user_id=session.user["user_id"],
        code=payload.code,
        ip=_client_ip(request),
        user_agent=_user_agent(request),
    )
    return TotpEnableResponse(**result)


@router.post(
    "/2fa/disable",
    response_model=UserResponse,
    dependencies=[Depends(require_csrf)],
)
@limiter.limit("10/minute")
def disable_two_factor(
    request: Request,
    payload: TwoFactorDisableRequest,
    session: auth_service.SessionContext = Depends(require_user),
) -> UserResponse:
    result = auth_service.disable_two_factor(
        user_id=session.user["user_id"],
        password=payload.password,
        code=payload.code,
        ip=_client_ip(request),
        user_agent=_user_agent(request),
    )
    return UserResponse(**result)


@router.post(
    "/2fa/recovery-codes",
    response_model=RecoveryCodesResponse,
    dependencies=[Depends(require_csrf)],
)
@limiter.limit("5/minute")
def regenerate_recovery_codes(
    request: Request,
    payload: RecoveryCodesRequest,
    session: auth_service.SessionContext = Depends(require_user),
) -> RecoveryCodesResponse:
    result = auth_service.regenerate_recovery_codes(
        user_id=session.user["user_id"],
        password=payload.password,
        code=payload.code,
        ip=_client_ip(request),
        user_agent=_user_agent(request),
    )
    return RecoveryCodesResponse(**result)


@router.get("/google/start")
@limiter.limit("20/minute")
def google_start(
    request: Request,
    next_path: str = Query("/account", alias="next", max_length=500),
) -> RedirectResponse:
    callback_url = google_service.redirect_uri(str(request.base_url))
    start = auth_service.build_google_start(
        next_path=next_path,
        link_user_id=None,
        callback_url=callback_url,
    )
    redirect = RedirectResponse(start["url"], status_code=302)
    _set_oauth_state_cookie(redirect, start["state"])
    return redirect


@router.post(
    "/google/connect",
    response_model=GoogleStartResponse,
    dependencies=[Depends(require_csrf)],
)
@limiter.limit("10/minute")
def google_connect(
    request: Request,
    response: Response,
    session: auth_service.SessionContext = Depends(require_user),
) -> GoogleStartResponse:
    callback_url = google_service.redirect_uri(str(request.base_url))
    start = auth_service.build_google_start(
        next_path="/account",
        link_user_id=session.user["user_id"],
        callback_url=callback_url,
    )
    _set_oauth_state_cookie(response, start["state"])
    return GoogleStartResponse(url=start["url"])


@router.get("/google/callback")
@limiter.limit("30/minute")
def google_callback(
    request: Request,
    code: str = Query("", max_length=4096),
    state: str = Query("", max_length=500),
    error: str = Query("", max_length=200),
) -> RedirectResponse:
    if error:
        return _login_error_redirect(request, "google_denied", clear_state=True)
    state_cookie = request.cookies.get(OAUTH_STATE_COOKIE)
    if not code or not state or not state_cookie or not hmac.compare_digest(state, state_cookie):
        return _login_error_redirect(request, "google_state")
    callback_url = google_service.redirect_uri(str(request.base_url))
    try:
        result = auth_service.complete_google(
            state=state,
            code=code,
            callback_url=callback_url,
            ip=_client_ip(request),
            user_agent=_user_agent(request),
        )
    except AuthError as exc:
        return _login_error_redirect(request, exc.code, clear_state=True)
    except google_service.GoogleAuthError as exc:
        return _login_error_redirect(request, exc.code, clear_state=True)
    except Exception as exc:
        import logging

        logging.getLogger("app.auth.google").exception("Google callback failed: %s", exc)
        return _login_error_redirect(request, "google_failed", clear_state=True)

    if result.challenge_token:
        fragment = urlencode(
            {"two-factor": result.challenge_token, "next": result.next_path}
        )
        response = RedirectResponse(
            f"{_app_base(request)}/login#{fragment}", status_code=302
        )
    else:
        response = RedirectResponse(
            f"{_app_base(request)}{result.next_path}", status_code=302
        )
    if result.token and result.expires_at:
        _set_session_cookie(response, result.token, result.expires_at)
    _set_csrf_cookie(response)
    _clear_oauth_state_cookie(response)
    return response


@router.post(
    "/google/unlink",
    response_model=UserResponse,
    dependencies=[Depends(require_csrf)],
)
@limiter.limit("10/minute")
def google_unlink(
    request: Request,
    payload: GoogleUnlinkRequest,
    session: auth_service.SessionContext = Depends(require_user),
) -> UserResponse:
    result = auth_service.unlink_google(
        user_id=session.user["user_id"],
        password=payload.password,
        ip=_client_ip(request),
        user_agent=_user_agent(request),
    )
    return UserResponse(**result)


@router.post(
    "/account/delete",
    response_model=ActionResponse,
    dependencies=[Depends(require_csrf)],
)
@limiter.limit("5/minute")
def delete_account(
    request: Request,
    response: Response,
    payload: DeleteAccountRequest,
    session: auth_service.SessionContext = Depends(require_user),
) -> ActionResponse:
    result = auth_service.delete_account(
        user_id=session.user["user_id"],
        password=payload.password,
        confirm_email=str(payload.confirm_email),
        code=payload.code,
        ip=_client_ip(request),
        user_agent=_user_agent(request),
    )
    _clear_session_cookie(response)
    _set_csrf_cookie(response)
    return ActionResponse(**result)
