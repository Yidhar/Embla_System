"""
Local-only auth stub.

This module intentionally disables all remote authentication flows.
It keeps the original function signatures so existing imports remain valid.
"""

from __future__ import annotations

from typing import Optional

LOCAL_ONLY_MODE = True

# Remote endpoints are intentionally blank in local-only mode.
BUSINESS_URL = ""
NAGA_MODEL_URL = ""
NAGA_MEMORY_URL = "local://memory"

_access_token: Optional[str] = None
_user_info: Optional[dict] = None


def _disabled_error(action: str) -> RuntimeError:
    return RuntimeError(f"Remote auth is disabled in local-only mode ({action})")


async def get_captcha() -> dict:
    raise _disabled_error("captcha")


async def login(username: str, password: str, captcha_id: str = "", captcha_answer: str = "") -> dict:
    raise _disabled_error("login")


async def get_me(token: Optional[str] = None) -> Optional[dict]:
    return None


async def refresh(refresh_token_override: Optional[str] = None) -> dict:
    raise _disabled_error("refresh")


def logout():
    global _access_token, _user_info
    _access_token = None
    _user_info = None


def is_authenticated() -> bool:
    return False


def has_refresh_token() -> bool:
    return False


def restore_token(token: str):
    # Keep as no-op in local-only mode.
    return None


def get_access_token() -> Optional[str]:
    return None


def get_user_info() -> Optional[dict]:
    return _user_info


async def register(username: str, email: str, password: str, verification_code: str) -> dict:
    raise _disabled_error("register")


async def send_verification(email: str, username: str, captcha_id: str = "", captcha_answer: str = "") -> dict:
    raise _disabled_error("send-verification")
