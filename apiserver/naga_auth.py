"""
NagaCAS 认证模块
对接 NagaCAS 统一认证服务，管理用户登录态
"""

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

CAS_URL = "http://62.234.131.204:30001"
NAGA_MODEL_URL = "http://62.234.131.204:30011"

# 模块级认证状态（单用户场景）
_access_token: Optional[str] = None
_refresh_token: Optional[str] = None
_user_info: Optional[dict] = None


async def login(username: str, password: str) -> dict:
    """通过 NagaCAS 登录，返回 token 和用户信息"""
    global _access_token, _refresh_token, _user_info
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(f"{CAS_URL}/auth/login", json={"username": username, "password": password})
        resp.raise_for_status()
        data = resp.json()

    _access_token = data.get("access_token") or data.get("accessToken")
    _refresh_token = data.get("refresh_token") or data.get("refreshToken")

    if not _access_token:
        raise ValueError("登录响应中缺少 access_token")

    # 登录成功后获取用户信息；若 /auth/me 不可用，从 login 响应中回退
    me = await get_me(_access_token)
    if me:
        _user_info = me
    else:
        _user_info = {"username": username}

    return {
        "success": True,
        "user": _user_info,
        "access_token": _access_token,
        "refresh_token": _refresh_token,
    }


async def get_me(token: Optional[str] = None) -> Optional[dict]:
    """通过 token 获取当前用户信息"""
    t = token or _access_token
    if not t:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{CAS_URL}/auth/me", headers={"Authorization": f"Bearer {t}"})
            if resp.status_code != 200:
                return None
            return resp.json()
    except Exception as e:
        logger.warning(f"获取用户信息失败: {e}")
        return None


async def refresh(refresh_token: str) -> dict:
    """使用 refresh_token 刷新 access_token"""
    global _access_token, _refresh_token
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(f"{CAS_URL}/oauth/token", json={"refresh_token": refresh_token})
        resp.raise_for_status()
        data = resp.json()

    _access_token = data.get("access_token") or data.get("accessToken")
    new_refresh = data.get("refresh_token") or data.get("refreshToken")
    if new_refresh:
        _refresh_token = new_refresh

    return {"access_token": _access_token, "refresh_token": _refresh_token}


def logout():
    """清除本地认证状态"""
    global _access_token, _refresh_token, _user_info
    _access_token = None
    _refresh_token = None
    _user_info = None


def is_authenticated() -> bool:
    return _access_token is not None


def get_access_token() -> Optional[str]:
    return _access_token


def get_user_info() -> Optional[dict]:
    return _user_info
