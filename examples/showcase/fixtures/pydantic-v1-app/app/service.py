from app.models import UserProfile


def public_payload(profile: UserProfile) -> dict[str, object]:
    return profile.dict(exclude_none=True)


def profile_from_record(record: object) -> UserProfile:
    return UserProfile.from_orm(record)
