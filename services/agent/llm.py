# ============================================
# services/agent/llm.py
# ============================================
"""
LLM factory for the Agent service.

Builds the chat model from the PRIMARY provider first. The backup provider
(API_KEY_2, official OpenAI restricted to gpt-5-nano) is activated only when
the primary key is rejected (HTTP 401) or its quota is exhausted (HTTP 403),
so a broken/expired/starved primary key never takes the whole system down.
"""

import logging

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI
from openai import AuthenticationError

from .config import settings

logger = logging.getLogger(__name__)


def _build_chat_model(model: str, api_key: str, base_url: str) -> ChatOpenAI:
    """
    Build a ChatOpenAI instance with explicit credentials.

    Passing api_key/base_url explicitly prevents the client from silently
    picking up a stale OPENAI_API_KEY from the shell environment.

    Args:
        model: Model name exposed by the provider.
        api_key: Provider API key.
        base_url: OpenAI-compatible API base URL.

    Returns:
        A configured ChatOpenAI instance.
    """
    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=0.0,
        timeout=90.0,
        max_retries=1,
    )


def _is_authentication_failure(error: Exception) -> bool:
    """
    Decide whether an error means the API key cannot serve requests.

    Two credential-level failures trigger failover:
    - HTTP 401: the provider rejected the key (invalid/expired).
    - HTTP 403 with an exhausted-quota message: the key is valid but the
      account has no remaining budget, so every call fails until recharged.

    Any other 403 (rate limits, moderation, ...) is treated as transient.

    Args:
        error: Exception raised by the provider call.

    Returns:
        True when the provider rejected or starved the credentials.
    """
    if isinstance(error, AuthenticationError):
        return True
    status_code = getattr(error, "status_code", None)
    text = str(error).lower()
    auth_rejected = status_code == 401 or "invalid_api_key" in text
    quota_exhausted = status_code == 403 and ("quota" in text or "insufficient" in text)
    return auth_rejected or quota_exhausted


def _validate_llm(llm: BaseChatModel) -> Exception | None:
    """
    Send a tiny probe request to verify that the credentials work.

    Args:
        llm: Chat model to validate.

    Returns:
        None when the probe succeeds, otherwise the raised exception.
    """
    try:
        llm.invoke("ping")
        return None
    except Exception as error:  # noqa: BLE001 - probe must never crash startup
        return error


def build_chat_llm() -> ChatOpenAI:
    """
    Build the chat model used by the whole agent graph.

    The primary provider is validated at startup. When it fails with a
    credential-level error (401 invalid key, or 403 exhausted quota), the
    factory switches to the backup provider (API_KEY_2). Any other error keeps
    the primary provider, because transient network issues should not burn the
    backup key.

    Returns:
        A validated ChatOpenAI instance.

    Raises:
        RuntimeError: When neither primary nor backup credentials are usable.
    """
    primary = _build_chat_model(settings.LLM_MODEL, settings.API_KEY, settings.BASE_URL)
    error = _validate_llm(primary)

    if error is None:
        logger.info("LLM ready: primary provider model=%s", settings.LLM_MODEL)
        return primary

    if not _is_authentication_failure(error) or not settings.API_KEY_2:
        raise RuntimeError(f"Primary LLM provider is unreachable: {error}")

    logger.warning(
        "Primary API key unusable (%s). Falling back to API_KEY_2 model=%s",
        getattr(error, "status_code", "auth error"),
        settings.API_KEY_2_MODEL,
    )
    backup = _build_chat_model(
        settings.API_KEY_2_MODEL, settings.API_KEY_2, settings.API_KEY_2_BASE_URL
    )
    backup_error = _validate_llm(backup)
    if backup_error is not None:
        raise RuntimeError(f"Backup LLM provider also failed: {backup_error}")

    logger.info("LLM ready: backup provider model=%s", settings.API_KEY_2_MODEL)
    return backup
