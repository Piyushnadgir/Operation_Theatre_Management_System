from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import decode_access_token

<<<<<<< HEAD
security = HTTPBearer()
=======
# auto_error=False so that a missing token gives 401 (as in the SAD) instead of
# FastAPI's default 403.
security = HTTPBearer(auto_error=False)

_UNAUTHORIZED_HEADERS = {"WWW-Authenticate": "Bearer"}
>>>>>>> 6d57647 (OTMS-16: Implement login, password hashing, lockout and RBAC middleware)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
<<<<<<< HEAD
    token = credentials.credentials
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
=======
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers=_UNAUTHORIZED_HEADERS,
        )
    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers=_UNAUTHORIZED_HEADERS,
>>>>>>> 6d57647 (OTMS-16: Implement login, password hashing, lockout and RBAC middleware)
        )
    return payload


def require_roles(*roles):
<<<<<<< HEAD
    def role_checker(user=Depends(get_current_user)):
        user_role = user.get("role")
        if user_role not in roles:
=======
    """Server-side RBAC (OT-SR-003). Deny by default: only the listed roles pass."""
    allowed = {getattr(role, "value", role) for role in roles}

    def role_checker(user=Depends(get_current_user)):
        if user.get("role") not in allowed:
>>>>>>> 6d57647 (OTMS-16: Implement login, password hashing, lockout and RBAC middleware)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions"
            )
        return user

    return role_checker
