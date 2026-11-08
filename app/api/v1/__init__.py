from fastapi import APIRouter

<<<<<<< HEAD
from app.api.v1 import surgeries

api_router = APIRouter()
=======
from app.api.v1 import auth, shifts, staff, surgeries

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(staff.router)
api_router.include_router(shifts.router)
>>>>>>> 6d57647 (OTMS-16: Implement login, password hashing, lockout and RBAC middleware)
api_router.include_router(surgeries.router)
