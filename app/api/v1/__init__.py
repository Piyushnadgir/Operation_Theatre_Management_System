from fastapi import APIRouter

from app.api.v1 import allocations, auth, equipment, reports, shifts, staff, surgeries, theatres

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(staff.router)
api_router.include_router(shifts.router)
api_router.include_router(surgeries.router)
api_router.include_router(equipment.router)
api_router.include_router(theatres.router)
api_router.include_router(allocations.router)
api_router.include_router(reports.router)
