"""
NagaBusiness 认证模块
对接 NagaBusiness 统一网关，管理用户登录态
"""

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# NagaBusiness 统一网关地址（对外唯一暴露的服务）
BUSINESS_URL = "http://62.234.131.204:30031"
# 兼容旧代码，LLM 调用也走 NagaBusiness
NAGA_MODEL_URL = BUSINESS_URL
# NagaMemory 远程记忆服务地址（NebulaGraph 后端）
NAGA_MEMORY_URL = f"{BUSINESS_URL}/api/memory"

# 模块级认证状态（单用户场景）
_access_token: Optional[str] = None
_refresh_token: Optional[str] = None
_user_info: Optional[dict] = None


async def get_captcha() -> dict:
    """获取验证码（数学计算题）"""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{BUSINESS_URL}/api/auth/captcha")
        resp.raise_for_status()
        return resp.json()


async def login(username: str, password: str, captcha_id: str = "", captcha_answer: str = "") -> dict:
    """通过 NagaBusiness 登录，返回 token 和用户信息"""
    global _access_token, _refresh_token, _user_info
    payload: dict = {"username": username, "password": password}
    if captcha_id and captcha_answer:
        payload["captcha_id"] = captcha_id
        payload["captcha_answer"] = captcha_answer
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(f"{BUSINESS_URL}/api/auth/login", json=payload)
        if resp.status_code != 200:
            logger.error(f"NagaBusiness login 返回 {resp.status_code}: {resp.text}")
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
        "memory_url": NAGA_MEMORY_URL,
    }


async def get_me(token: Optional[str] = None) -> Optional[dict]:
    """通过 token 获取当前用户信息"""
    t = token or _access_token
    if not t:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{BUSINESS_URL}/api/auth/me", headers={"Authorization": f"Bearer {t}"})
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
        resp = await client.post(f"{BUSINESS_URL}/api/auth/refresh", json={"refresh_token": refresh_token})
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


async def register(username: str, email: str, password: str, verification_code: str) -> dict:
    """通过 NagaBusiness 注册新用户"""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{BUSINESS_URL}/api/auth/register",
            json={"username": username, "email": email, "password": password, "verification_code": verification_code},
        )
        resp.raise_for_status()
        return resp.json()


async def send_verification(email: str, username: str, captcha_id: str = "", captcha_answer: str = "") -> dict:
    """发送邮箱验证码"""
    payload: dict = {"email": email, "username": username}
    if captcha_id and captcha_answer:
        payload["captcha_id"] = captcha_id
        payload["captcha_answer"] = captcha_answer
    logger.info(f"send_verification payload: {payload}")
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{BUSINESS_URL}/api/auth/send-verification",
            json=payload,
        )
        if resp.status_code != 200:
            logger.error(f"NagaBusiness send-verification 返回 {resp.status_code}: {resp.text}")
        resp.raise_for_status()
        return resp.json()
