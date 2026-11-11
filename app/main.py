from fastapi import FastAPI

from app.api.v1 import api_router
from app.core.config import settings
from app.core.database import Base, engine
from app.core.https import EnforceHTTPSMiddleware

Base.metadata.create_all(bind=engine)

app = FastAPI(title="OTMS API", version="1.0.0")

if settings.enforce_https:
    app.add_middleware(EnforceHTTPSMiddleware)

app.include_router(api_router, prefix="/api/v1")


@app.get("/health")
def health():
    return {"status": "healthy"}
