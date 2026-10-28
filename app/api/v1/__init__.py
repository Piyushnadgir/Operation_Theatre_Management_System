from fastapi import APIRouter

from app.api.v1 import surgeries

api_router = APIRouter()
api_router.include_router(surgeries.router)
