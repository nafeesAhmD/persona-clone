from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.schemas.auth import UserRead, UserUpdate
from app.services import auth_service

router = APIRouter(prefix="/users", tags=["users"])


@router.patch("/me", response_model=UserRead)
def update_me(data: UserUpdate, user: CurrentUser, db: DbSession) -> UserRead:
    """Update your own full name and/or username. Other fields are rejected."""
    return UserRead.model_validate(auth_service.update_profile(db, user, data))
