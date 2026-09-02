from __future__ import annotations


class ControlRoomError(ValueError):
    """Base error for invalid local Project Control Room state."""


class InvalidControlRoom(ControlRoomError):
    """Raised when a coordination record is malformed or incomplete."""


class DependencyUnavailable(ControlRoomError):
    """Raised when an optional local dependency cannot be used safely."""


class RemotePartialFailure(ControlRoomError):
    """Raised when a remote reconciliation completed only partially."""
