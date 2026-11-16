from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1 import api_router
from app.core.config import settings
from app.core.database import Base, engine
from app.core.https import EnforceHTTPSMiddleware

Base.metadata.create_all(bind=engine)

app = FastAPI(title="OTMS API", version="1.0.0")

if settings.enforce_https:
    app.add_middleware(EnforceHTTPSMiddleware)

app.include_router(api_router, prefix="/api/v1")

# Web UI (SAD 3.3): plain HTML, CSS and JavaScript served from app/static at /ui
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/ui", StaticFiles(directory=STATIC_DIR, html=True), name="ui")


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/ui/")


@app.get("/health")
def health():
    return {"status": "healthy"}
