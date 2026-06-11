from app.core.workers.auth_errors import detect_auth_failure


def test_detects_anthropic_401_envelope():
    out = (
        '{"type":"error","error":{"type":"authentication_error",'
        '"message":"Invalid authentication credentials"}}'
    )
    msg = detect_auth_failure(out, "")
    assert msg is not None
    assert "credentials" in msg.lower()


def test_detects_failed_to_authenticate_text():
    assert detect_auth_failure("", "Failed to authenticate. API Error: 401") is not None


def test_clean_output_is_not_flagged():
    assert detect_auth_failure("Added subtract(a, b) to calc.py", "") is None
