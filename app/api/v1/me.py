from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.schemas.surgery import SurgeryResponse
from app.services.my_surgeries import upcoming_surgeries_for_user

router = APIRouter(prefix="/me", tags=["Me"])


@router.get("/surgeries", response_model=List[SurgeryResponse])
def my_upcoming_surgeries(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """SAD 4.5: doctors and nurses see their own upcoming surgeries."""
    try:
        user_id = int(current_user.get("sub"))
    except (TypeError, ValueError):
        return []
    return upcoming_surgeries_for_user(db, user_id, datetime.now())
