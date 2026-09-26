# ============================================
# services/identity/security/hashing.py
# ============================================
"""
Password hashing primitives (bcrypt).
"""

import bcrypt


def hash_password(password: str) -> str:
    """
    Hash a plain password with bcrypt.

    Args:
        password: Plain-text password from the register/login request.

    Returns:
        The bcrypt hash as a UTF-8 string.
    """
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """
    Check a plain password against a stored bcrypt hash.

    Args:
        password: Plain-text password candidate.
        password_hash: Stored bcrypt hash.

    Returns:
        True when the password matches.
    """
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False
