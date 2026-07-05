from protean.testing import _flatten_messages


def test_flatten_messages_from_dict():
    messages = {"field_a": ["msg1", "msg2"], "field_b": ["msg3"]}

    assert _flatten_messages(messages) == ["msg1", "msg2", "msg3"]


def test_flatten_messages_from_string():
    # A bare string is wrapped into a single-element list.
    assert _flatten_messages("boom") == ["boom"]


def test_flatten_messages_from_list():
    # A list of messages is returned as a new list.
    result = _flatten_messages(["a", "b"])

    assert result == ["a", "b"]
