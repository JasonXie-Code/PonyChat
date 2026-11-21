import pytest
from Backend.chat_modules.harness_runtime import _closed_schema, _validate_arguments


def test_nullable_memory_timestamp_validates_null_and_string():
    schema = _closed_schema({"type": "object", "properties": {"occurred_at": {
        "type": ["string", "null"], "minLength": 1, "maxLength": 80}}, "required": ["occurred_at"]})
    for value in (None, "2026-09-13T12:00:00+08:00"):
        _validate_arguments({"occurred_at": value}, schema)
    for value in ("", 123, False, "x" * 81):
        with pytest.raises(ValueError):
            _validate_arguments({"occurred_at": value}, schema)


@pytest.mark.parametrize("kind", [["string", "integer"], ["null", "null"], ["string", "null", "integer"], [["string"], "null"]])
def test_unsupported_union_fails_closed(kind):
    with pytest.raises(ValueError):
        _closed_schema({"type": kind})
