from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import jwt  # PyJWT
from app.core.config import settings
from app.core.database import get_db
from app.modules.audit.listener import set_actor
from app.modules.users.models import User
from sqlalchemy.orm import Session
from typing import List

# This tells FastAPI to automatically look for the token in the HTTP "Authorization" header
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> dict:
    """Return the active, current database identity represented by a JWT.

    The database is the source of truth for a user's role, active state, and
    tenant, preventing stale token claims from bypassing tenant isolation.
    """
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        user_id: str = payload.get("sub")
        role: str = payload.get("role")
        company_id: str = payload.get("company_id")
        if user_id is None or role is None or company_id is None:
            raise HTTPException(status_code=401, detail="Invalid token payload")
        user = db.query(User).filter(User.id == user_id).first()
        if not user or not user.is_active:
            raise HTTPException(status_code=401, detail="Inactive or unknown user")
        if str(user.company_id) != company_id:
            raise HTTPException(status_code=401, detail="Invalid token payload")

        # Tag the request's session with who is acting, so the audit listener can
        # attribute every change made downstream. Done here because this is the
        # one place that has both a verified identity and the session the
        # endpoint will use — FastAPI caches get_db per request, so the endpoint
        # receives this same Session object.
        set_actor(db, user_id=user.id, company_id=user.company_id)

        return {
            "id": str(user.id),
            "role": user.role,
            "company_id": str(user.company_id),
        }
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


class RequireRole:
    """
    A class used to check permissions.
    Usage: Depends(RequireRole(["admin", "finance"]))
    """

    def __init__(self, allowed_roles: List[str]):
        self.allowed_roles = allowed_roles

    def __call__(self, user: dict = Depends(get_current_user)):
        # If the user's role isn't on the list, block them!
        if user["role"] not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action.",
            )
        return user
