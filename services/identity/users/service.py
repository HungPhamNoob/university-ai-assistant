# ============================================
# services/identity/users/service.py
# ============================================
"""
Business logic of the users feature: register, login, profile.
All operations run against the real Postgres database through the repository.
"""

import logging

from ..security.hashing import hash_password, verify_password
from ..security.tokens import create_access_token
from .models import User
from .repository import UserRepository
from .schemas import AuthResponse, LoginRequest, RegisterRequest, UserProfile

logger = logging.getLogger(__name__)


class EmailAlreadyRegisteredError(Exception):
    """Raised when registration reuses an existing email."""


class InvalidCredentialsError(Exception):
    """Raised when login email/password do not match any user."""


class AuthService:
    """Use-case layer orchestrating user authentication."""

    def __init__(self, repository: UserRepository):
        """
        Args:
            repository: Data access object for users.
        """
        self._repository = repository

    async def register(self, data: RegisterRequest) -> AuthResponse:
        """
        Register a new user and immediately return a JWT.

        Args:
            data: Registration payload (email, password, name).

        Returns:
            AuthResponse with the issued token and the user profile.

        Raises:
            EmailAlreadyRegisteredError: When the email already exists.
        """
        email = str(data.email).lower()
        existing = await self._repository.get_by_email(email)
        if existing is not None:
            raise EmailAlreadyRegisteredError(f"Email '{email}' is already registered")

        user = User(
            email=email,
            password_hash=hash_password(data.password),
            name=data.name.strip(),
        )
        saved = await self._repository.create(user)
        logger.info("User registered id=%s email=%s", saved.user_id, saved.email)
        return self._build_auth_response(saved)

    async def login(self, data: LoginRequest) -> AuthResponse:
        """
        Authenticate an existing user and return a JWT.

        Args:
            data: Login payload (email, password).

        Returns:
            AuthResponse with the issued token and the user profile.

        Raises:
            InvalidCredentialsError: When email or password is wrong.
        """
        user = await self._repository.get_by_email(str(data.email).lower())
        if user is None or not verify_password(data.password, user.password_hash):
            raise InvalidCredentialsError("Invalid email or password")
        logger.info("User logged in id=%s", user.user_id)
        return self._build_auth_response(user)

    async def get_profile(self, user_id: str) -> UserProfile:
        """
        Fetch the profile of one user.

        Args:
            user_id: Unique user identifier.

        Returns:
            The user profile.

        Raises:
            InvalidCredentialsError: When the user id does not exist.
        """
        user = await self._repository.get_by_id(user_id)
        if user is None:
            raise InvalidCredentialsError("Unknown user id")
        return UserProfile.model_validate(user)

    def _build_auth_response(self, user: User) -> AuthResponse:
        """Build the AuthResponse (JWT + profile) for one user entity."""
        token = create_access_token(user.user_id, user.email, user.name)
        return AuthResponse(token=token, user=UserProfile.model_validate(user))
