"""OT-SR-001: refuse plain HTTP and tell browsers to keep using HTTPS."""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class EnforceHTTPSMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # Behind a reverse proxy run uvicorn with --proxy-headers so that the
        # scheme reflects the client's original connection.
        if request.url.scheme != "https":
            return JSONResponse(
                status_code=403,
                content={
                    "detail": {
                        "error": "HttpsRequired",
                        "message": "This API is only available over HTTPS (TLS 1.2 or higher)",
                    }
                },
            )
        response = await call_next(request)
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response
