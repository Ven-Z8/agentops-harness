from pydantic import BaseModel, validator


class UserProfile(BaseModel):
    user_id: int
    email: str
    display_name: str | None = None

    @validator("email")
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()

    class Config:
        orm_mode = True
        # Current Pydantic 2 no longer maps ``orm_mode`` to this runtime flag. Keep
        # the v1 seam above while allowing the legacy ``from_orm`` path to run.
        from_attributes = True
