from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.rate_limit import limiter
from app.core.security import create_access_token, get_password_hash, verify_password
from app.core.dependencies import RequireRole
from app.modules.users.models import User
from app.modules.users.schemas import Token, UserCreate, UserLogin, UserResponse

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])

# Lockout policy. Rate limiting alone only slows down one source; a distributed
# guessing attempt still gets unlimited tries at a single account.
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION = timedelta(minutes=15)

# Comparing against this when no user exists keeps the failure path the same
# shape as a wrong-password failure. bcrypt is deliberately slow (~200ms), so
# short-circuiting on an unknown email made "no such user" return in ~1ms and
# "wrong password" in ~200ms — a timing side channel that lets an attacker
# harvest valid email addresses, which is exactly the input list a credential
# stuffing run needs. Computed once at import.
_DUMMY_HASH = get_password_hash("a-password-that-is-never-correct")

_INVALID_CREDENTIALS = "Incorrect email or password"


@router.post(
    "/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED
)
def register(
    user_in: UserCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(RequireRole(["admin"])),
):
    """Provision a user within the authenticated admin's tenant.

    Initial tenant administrators must be created by a trusted bootstrap process
    (for example the seed/operations workflow), not through a public endpoint.
    """
    user = db.query(User).filter(User.email == user_in.email).first()
    if user:
        raise HTTPException(status_code=400, detail="Email already registered")

    try:
        new_user = User(
            email=user_in.email,
            hashed_password=get_password_hash(user_in.password),
            company_id=current_user["company_id"],
            role=user_in.role,
            is_active=True,
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        return new_user
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Invalid data provided")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


def _register_failure(db: Session, user: User | None) -> None:
    """Count a failed attempt and lock the account once the threshold is hit."""
    if user is None:
        return

    user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
    if user.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
        user.locked_until = datetime.now(timezone.utc) + LOCKOUT_DURATION
    db.commit()


@router.post("/login", response_model=Token)
@limiter.limit("5/minute")
def login(request: Request, user_in: UserLogin, db: Session = Depends(get_db)):
    """Exchange credentials for a signed access token.

    Rate limited because login is the one endpoint where guessing pays off: with
    no limit, the blanket 10 requests/second at the proxy allowed 600 password
    attempts per minute per address.
    """
    user = db.query(User).filter(User.email == user_in.email).first()

    if user is not None and user.locked_until is not None:
        if user.locked_until > datetime.now(timezone.utc):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Account temporarily locked after repeated failed attempts. Try again later.",
            )
        # Lock expired — start the user with a clean slate.
        user.locked_until = None
        user.failed_login_attempts = 0

    # Always run a hash comparison, even with no matching user, so the response
    # time does not reveal whether the address is registered.
    password_matches = verify_password(
        user_in.password, user.hashed_password if user else _DUMMY_HASH
    )

    if user is None or not password_matches:
        _register_failure(db, user)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=_INVALID_CREDENTIALS
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive user"
        )

    # Successful authentication clears the lockout counters.
    if user.failed_login_attempts or user.locked_until:
        user.failed_login_attempts = 0
        user.locked_until = None
    db.commit()

    access_token = create_access_token(
        data={
            "sub": str(user.id),
            "role": user.role,
            "company_id": str(user.company_id),
        }
    )

    return {"access_token": access_token, "token_type": "bearer"}
