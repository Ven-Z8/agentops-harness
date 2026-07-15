from types import SimpleNamespace

from app.models import UserProfile
from app.service import profile_from_record, public_payload


def test_public_payload_normalizes_email_and_omits_none() -> None:
    profile = UserProfile(user_id=7, email="  USER@EXAMPLE.COM  ")

    assert public_payload(profile) == {"user_id": 7, "email": "user@example.com"}


def test_profile_from_record_reads_object_attributes() -> None:
    record = SimpleNamespace(user_id=8, email="person@example.com", display_name="Person")

    assert profile_from_record(record).display_name == "Person"
