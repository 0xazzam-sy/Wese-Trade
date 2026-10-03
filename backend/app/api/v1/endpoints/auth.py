"""Authentication routes. Thin HTTP layer over `user_service`."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.api.deps import CurrentUser, OptionalUser, Resources, SessionDep
from app.auth.tokens import ACCESS_COOKIE_NAME, create_access_token
from app.core.config import API_V1_PREFIX
from app.core.logging import get_logger
from app.schemas.auth import LoginRequest, LoginResponse, SessionResponse
from app.schemas.user import UserPublic
from app.services.user_service import authenticate, normalize_username

router = APIRouter(prefix="/auth", tags=["auth"])
logger = get_logger(__name__)

COOKIE_PATH = API_V1_PREFIX


def _client_key(request: Request) -> str:
    host = request.client.host if request.client else "unknown"
    return f"ip:{host}"


@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: SessionDep,
    resources: Resources,
) -> LoginResponse:
    settings = resources.settings
    limiter = resources.login_limiter
    keys = (f"user:{normalize_username(payload.username)}", _client_key(request))

    if (retry_after := limiter.retry_after(*keys)) > 0:
        logger.warning("auth.login.throttled", extra={"fields": {"retry_after": retry_after}})
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too_many_attempts",
            headers={"Retry-After": str(retry_after)},
        )

    user = await authenticate(session, username=payload.username, password=payload.password)
    if user is None:
        limiter.record_failure(*keys)
        logger.info("auth.login.failed")
        # Generic message: never reveal whether the username exists.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_credentials")

    limiter.reset(*keys)
    issued = create_access_token(
        user_id=user.id,
        secret_key=settings.secret_key,
        expire_minutes=settings.access_token_expire_minutes,
    )
    response.set_cookie(
        key=ACCESS_COOKIE_NAME,
        value=issued.token,
        max_age=settings.access_token_expire_minutes * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path=COOKIE_PATH,
    )
    logger.info("auth.login.succeeded", extra={"fields": {"user_id": user.id}})
    return LoginResponse(user=UserPublic.model_validate(user), expires_at=issued.expires_at)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response, resources: Resources) -> Response:
    response.delete_cookie(
        key=ACCESS_COOKIE_NAME,
        path=COOKIE_PATH,
        httponly=True,
        secure=resources.settings.cookie_secure,
        samesite="strict",
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=UserPublic)
async def me(user: CurrentUser) -> UserPublic:
    return UserPublic.model_validate(user)


@router.get("/session", response_model=SessionResponse)
async def current_session(user: OptionalUser) -> SessionResponse:
    if user is None:
        return SessionResponse(authenticated=False, user=None)
    return SessionResponse(authenticated=True, user=UserPublic.model_validate(user))
