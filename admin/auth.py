"""
管理面板鉴权
独立模块，避免 admin_server ↔ routers 的循环导入。
"""

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from core.config_loader import get_config

security = HTTPBearer(auto_error=False)


def verify_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """简单的 Bearer Token 校验，token 来自 config.admin.secret_key"""
    secret = get_config().get("admin", {}).get("secret_key", "")
    if not credentials or credentials.credentials != secret:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True
