from fastapi import HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute

from app.services.equipment_service import InvalidRequest, ResourceConflict, ResourceNotFound


class ResourceRoute(APIRoute):
    """Turns validation and service errors into the status codes in SAD 4.3.

    FastAPI answers bad input with 422 by default, but the SAD says 400. Only the
    equipment, theatre and allocation routers use this class, so /surgeries is unchanged.
    """

    def get_route_handler(self):
        route_handler = super().get_route_handler()

        async def handle_errors(request: Request):
            try:
                return await route_handler(request)
            except RequestValidationError as error:
                details = [
                    {"field": ".".join(str(part) for part in item["loc"]), "message": item["msg"]}
                    for item in error.errors()
                ]
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"error": "Bad Request", "message": "Invalid input", "details": details},
                )
            except InvalidRequest as error:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"error": "Bad Request", "message": str(error)},
                )
            except ResourceNotFound as error:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"error": "Not Found", "message": str(error)},
                )
            except ResourceConflict as error:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"error": "Conflict", "message": str(error), "conflicts": error.conflicts},
                )

        return handle_errors
