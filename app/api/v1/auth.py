from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_roles
from app.models.models import RoleEnum
from app.schemas.auth import LoginRequest, LoginResponse, UserCreate, UserResponse
from app.services.audit_service import log_action
from app.services.auth_service import (
    AccountLockedError,
    AuthService,
    DuplicateUserError,
    InvalidCredentialsError,
)

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/login", response_model=LoginResponse)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    try:
        token, role = AuthService(db).authenticate(data.username, data.password)
    except AccountLockedError:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail={"error": "AccountLocked", "message": "Account is locked. Contact an administrator."},
        )
    except InvalidCredentialsError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "InvalidCredentials", "message": "Invalid username or password"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return {"token": token, "role": role}


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    data: UserCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_roles(RoleEnum.admin)),
):
    try:
        user = AuthService(db).create_user(data.username, data.password, data.role)
    except DuplicateUserError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "DuplicateUser", "message": "Username already exists"},
        )
    log_action(db, "user.create", user_id=current_user.get("sub"),
               entity_type="user", entity_id=user.user_id)
    return user


@router.post("/users/{user_id}/unlock")
def unlock_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_roles(RoleEnum.admin)),
):
    user = AuthService(db).unlock_user(user_id, acting_user_id=current_user.get("sub"))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "NotFound", "message": f"User {user_id} not found"},
        )
    return {"status": "unlocked"}
