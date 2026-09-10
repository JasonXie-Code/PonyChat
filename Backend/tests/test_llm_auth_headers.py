import pytest

from Backend.providers.llm_call import _auth_headers, _validated_request_headers


def test_auth_headers_strip_api_key_whitespace():
    assert _auth_headers({"model_name": "demo", "api_key": "  secret  "}) == {
        "Authorization": "Bearer secret",
        "Content-Type": "application/json",
    }


@pytest.mark.parametrize("api_key", [None, "", "   "])
def test_auth_headers_reject_missing_api_key(api_key):
    with pytest.raises(ValueError, match="demo.*missing api_key"):
        _auth_headers({"model_name": "demo", "api_key": api_key})


def test_explicit_headers_reject_empty_bearer():
    with pytest.raises(ValueError, match="demo.*missing api_key"):
        _validated_request_headers(
            {"Authorization": "Bearer ", "Content-Type": "application/json"},
            {"model_name": "demo", "api_key": ""},
        )


def test_explicit_headers_preserve_valid_authorization():
    headers = {"Authorization": "Bearer secret", "Content-Type": "application/json"}
    assert _validated_request_headers(headers, {"model_name": "demo"}) == headers
