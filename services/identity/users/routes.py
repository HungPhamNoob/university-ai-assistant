# ============================================
# services/identity/users/routes.py
# ============================================
"""
HTTP endpoints of the users feature.

- POST /auth/register and POST /auth/login are PUBLIC.
- GET /auth/me reads the caller identity from the X-User-Id header (injected
  by the API Gateway in production) or from an Authorization: Bearer JWT
  (direct access, e.g. the local CLI).
"""

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from ..security.tokens import decode_access_token
from .schemas import AuthResponse, LoginRequest, RegisterRequest, UserProfile
from .service import AuthService, EmailAlreadyRegisteredError, InvalidCredentialsError

router = APIRouter()


def get_service(request: Request) -> AuthService:
    """
    Resolve the AuthService instance created at application startup.

    Args:
        request: Incoming HTTP request carrying the application state.

    Returns:
        The shared AuthService.
    """
    return request.app.state.auth_service


@router.post("/register", response_model=AuthResponse, status_code=201)
async def register(
    payload: RegisterRequest, service: AuthService = Depends(get_service)
) -> AuthResponse:
    """
    Register a new user and return a JWT.

    Args:
        payload: Registration data.
        service: Injected auth use-case service.

    Returns:
        Token and user profile.
    """
    try:
        return await service.register(payload)
    except EmailAlreadyRegisteredError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/login", response_model=AuthResponse)
async def login(
    payload: LoginRequest, service: AuthService = Depends(get_service)
) -> AuthResponse:
    """
    Authenticate a user and return a JWT.

    Args:
        payload: Login credentials.
        service: Injected auth use-case service.

    Returns:
        Token and user profile.
    """
    try:
        return await service.login(payload)
    except InvalidCredentialsError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error


@router.get("/me", response_model=UserProfile)
async def me(
    service: AuthService = Depends(get_service),
    x_user_id: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> UserProfile:
    """
    Return the profile of the authenticated caller.

    Identity resolution order:
    1. X-User-Id header (trusted: injected by the API Gateway), then
    2. Authorization: Bearer <JWT> (direct access for local clients).

    Args:
        service: Injected auth use-case service.
        x_user_id: Gateway-injected user id header.
        authorization: Bearer token header.

    Returns:
        The user profile.
    """
    user_id = x_user_id
    if not user_id and authorization and authorization.lower().startswith("bearer "):
        claims = decode_access_token(authorization[7:].strip())
        if claims:
            user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing authentication")

    try:
        return await service.get_profile(user_id)
    except InvalidCredentialsError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
