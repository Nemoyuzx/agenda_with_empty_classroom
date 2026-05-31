from __future__ import annotations

import os

from ..errors import BuptServiceError


def resolve_credentials(account: str | None, password: str | None) -> tuple[str, str]:
    user = (account or os.getenv("BUPT_USERNAME") or "").strip()
    secret = password or os.getenv("BUPT_PASSWORD") or ""
    if not user or not secret:
        raise BuptServiceError("请填写学号和教务密码，或在后端环境变量中配置 BUPT_USERNAME/BUPT_PASSWORD。", 400)
    return user, secret
