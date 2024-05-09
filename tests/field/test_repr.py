from protean.fields import String, Text


def test_identifier_in_repr():
    email = String(identifier=True)
    ssn = String(identifier=True, required=True)

    assert repr(email) == str(email) == "String(identifier=True)"
    assert repr(ssn) == str(ssn) == "String(identifier=True)"


def test_required_in_repr():
    name = String(required=True)
    email = String(required=True, default="John Doe")

    assert repr(name) == str(name) == "String(required=True)"
    assert repr(email) == str(email) == "String(required=True, default='John Doe')"


def test_string_repr_and_str():
    str_obj1 = String(max_length=50)
    str_obj2 = String(min_length=50)
    str_obj3 = String(sanitize=False)
    str_obj4 = String(max_length=50, min_length=50, sanitize=False)
    str_obj5 = String(required=True, default="John Doe")
    str_obj6 = String(
        required=True, default="John Doe", min_length=50, max_length=50, sanitize=False
    )

    assert repr(str_obj1) == str(str_obj1) == "String(max_length=50)"
    assert repr(str_obj2) == str(str_obj2) == "String(min_length=50)"
    assert repr(str_obj3) == str(str_obj3) == "String(sanitize=False)"
    assert (
        repr(str_obj4)
        == str(str_obj4)
        == "String(max_length=50, min_length=50, sanitize=False)"
    )
    assert (
        repr(str_obj5) == str(str_obj5) == "String(required=True, default='John Doe')"
    )
    assert (
        repr(str_obj6)
        == str(str_obj6)
        == "String(required=True, default='John Doe', max_length=50, min_length=50, sanitize=False)"
    )


def test_text_repr_and_str():
    text_obj1 = Text(sanitize=False)
    text_obj2 = Text(required=True, default="John Doe")
    text_obj3 = Text(required=True, sanitize=False)
    text_obj4 = Text(required=True, default="John Doe", sanitize=False)

    assert repr(text_obj1) == str(text_obj1) == "Text(sanitize=False)"
    assert (
        repr(text_obj2) == str(text_obj2) == "Text(required=True, default='John Doe')"
    )
    assert repr(text_obj3) == str(text_obj3) == "Text(required=True, sanitize=False)"
    assert (
        repr(text_obj4)
        == str(text_obj4)
        == "Text(required=True, default='John Doe', sanitize=False)"
    )
