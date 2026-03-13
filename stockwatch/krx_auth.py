from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import requests
from pykrx.website.comm import webio

LOGIN_SUCCESS_CODE = "CD001"
LOGIN_FAILURE_CODE = "CD011"
LOGIN_DUPLICATE_CODE = "CD011"
DEFAULT_LOGIN_PAGE_URL = "https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001.cmd"
DEFAULT_LOGIN_JSP_URL = "https://data.krx.co.kr/contents/MDC/COMS/client/view/login.jsp?site=mdc"
DEFAULT_LOGIN_URL = "https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001D1.cmd"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_ORIGINAL_GET_READ = webio.Get.read
_ORIGINAL_POST_READ = webio.Post.read
_PATCHED = False


@dataclass
class KRXLoginResult:
    success: bool
    code: str | None
    message: str


def mask_credential(value: str | None, *, show: int = 2) -> str:
    if not value:
        return "<empty>"
    if len(value) <= show * 2:
        return "*" * len(value)
    return f"{value[:show]}{'*' * (len(value) - (show * 2))}{value[-show:]}"


def install_pykrx_session_wrappers(session: requests.Session) -> None:
    """Patch pykrx webio classes so all requests share the provided Session."""

    global _PATCHED
    if _PATCHED:
        return

    def _get_read(self: webio.Get, **params: Any) -> requests.Response:
        return session.get(self.url, headers=self.headers, params=params)

    def _post_read(self: webio.Post, **params: Any) -> requests.Response:
        return session.post(self.url, headers=self.headers, data=params)

    webio.Get.read = _get_read
    webio.Post.read = _post_read
    _PATCHED = True


def restore_pykrx_session_wrappers() -> None:
    global _PATCHED
    if not _PATCHED:
        return
    webio.Get.read = _ORIGINAL_GET_READ
    webio.Post.read = _ORIGINAL_POST_READ
    _PATCHED = False


def _extract_login_code_and_message(data: dict[str, Any]) -> tuple[str | None, str]:
    code = str(
        data.get("_error_code")
        or data.get("code")
        or data.get("resultCd")
        or data.get("RESULT_CD")
        or data.get("statusCd")
        or ""
    ).strip() or None
    message = str(
        data.get("_error_message")
        or data.get("message")
        or data.get("resultMsg")
        or data.get("RESULT_MSG")
        or data.get("msg")
        or ""
    ).strip() or "No message"
    return code, message


def login_krx(
    session: requests.Session,
    login_id: str,
    login_pw: str,
    *,
    logger: logging.Logger,
    login_url: str = DEFAULT_LOGIN_URL,
) -> KRXLoginResult:
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Referer": DEFAULT_LOGIN_PAGE_URL,
    }

    # 1) initialize session cookies/JSESSIONID
    session.get(DEFAULT_LOGIN_PAGE_URL, headers={"User-Agent": DEFAULT_USER_AGENT}, timeout=15)
    # 2) initialize login iframe context
    session.get(DEFAULT_LOGIN_JSP_URL, headers=headers, timeout=15)

    payload = {
        "mbrNm": "",
        "telNo": "",
        "di": "",
        "certType": "",
        "mbrId": login_id,
        "pw": login_pw,
    }

    response = session.post(login_url, data=payload, headers=headers, timeout=15)
    response.raise_for_status()

    try:
        data = response.json()
    except ValueError:
        logger.warning("KRX login response is not JSON. status=%s", response.status_code)
        return KRXLoginResult(success=False, code=None, message="Non-JSON login response")

    code, message = _extract_login_code_and_message(data)

    if code == LOGIN_DUPLICATE_CODE:
        payload["skipDup"] = "Y"
        response = session.post(login_url, data=payload, headers=headers, timeout=15)
        response.raise_for_status()
        try:
            data = response.json()
        except ValueError:
            logger.warning(
                "KRX duplicate-login retry response is not JSON. status=%s", response.status_code
            )
            return KRXLoginResult(success=False, code=None, message="Non-JSON duplicate retry response")
        code, message = _extract_login_code_and_message(data)

    if code == LOGIN_SUCCESS_CODE:
        return KRXLoginResult(success=True, code=code, message=message)

    if code == LOGIN_FAILURE_CODE:
        return KRXLoginResult(success=False, code=code, message=message)

    logger.warning("Unexpected KRX login response code=%s message=%s", code, message)
    return KRXLoginResult(success=False, code=code, message=message)
