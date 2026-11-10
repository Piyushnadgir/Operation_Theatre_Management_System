from fastapi import APIRouter

from app.api.v1 import allocations, equipment, surgeries, theatres

api_router = APIRouter()
api_router.include_router(surgeries.router)
api_router.include_router(equipment.router)
api_router.include_router(theatres.router)
api_router.include_router(allocations.router)
