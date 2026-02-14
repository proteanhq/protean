from datetime import datetime, timezone

from protean.fields import Auto, Float, Integer, String, Text


def utc_now():
    return datetime.now(timezone.utc)


def test_identifier_in_repr():
    email = String(identifier=True)
    ssn = String(identifier=True, required=True)

    assert repr(email) == str(email) == "String(identifier=True, max_length=255)"
    assert repr(ssn) == str(ssn) == "String(identifier=True, max_length=255)"


def test_required_in_repr():
    name = String(required=True)
    email = String(required=True, default="John Doe")

    assert repr(name) == str(name) == "String(required=True, max_length=255)"
    assert (
        repr(email)
        == str(email)
        == "String(required=True, default='John Doe', max_length=255)"
    )


def test_referenced_as_in_repr():
    name = String(referenced_as="fullname")
    email = String(required=True, referenced_as="email_address")

    assert repr(name) == str(name) == "String(referenced_as='fullname', max_length=255)"
    assert (
        repr(email)
        == str(email)
        == "String(required=True, referenced_as='email_address', max_length=255)"
    )


def test_description_in_repr():
    permit = String(description="Licences and Approvals", required=True)
    name = String(description="Full Name", required=True)

    assert (
        repr(permit)
        == str(permit)
        == "String(description='Licences and Approvals', required=True, max_length=255)"
    )
    assert (
        repr(name)
        == str(name)
        == "String(description='Full Name', required=True, max_length=255)"
    )


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
    assert repr(str_obj2) == str(str_obj2) == "String(max_length=255, min_length=50)"
    assert repr(str_obj3) == str(str_obj3) == "String(max_length=255, sanitize=False)"
    assert (
        repr(str_obj4)
        == str(str_obj4)
        == "String(max_length=50, min_length=50, sanitize=False)"
    )
    assert (
        repr(str_obj5)
        == str(str_obj5)
        == "String(required=True, default='John Doe', max_length=255)"
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


def test_integer_repr_and_str():
    int_obj1 = Integer(required=True)
    int_obj2 = Integer(required=True, default=100)
    int_obj3 = Integer(required=True, min_value=0, max_value=100)
    int_obj4 = Integer(required=True, default=100, min_value=0, max_value=100)

    assert repr(int_obj1) == str(int_obj1) == "Integer(required=True)"
    assert repr(int_obj2) == str(int_obj2) == "Integer(required=True, default=100)"
    assert (
        repr(int_obj3)
        == str(int_obj3)
        == "Integer(required=True, max_value=100, min_value=0)"
    )
    assert (
        repr(int_obj4)
        == str(int_obj4)
        == "Integer(required=True, default=100, max_value=100, min_value=0)"
    )


def test_float_repr_and_str():
    float_obj1 = Float(required=True)
    float_obj2 = Float(required=True, default=100.0)
    float_obj3 = Float(required=True, min_value=0.0, max_value=100.0)
    float_obj4 = Float(required=True, default=100.0, min_value=0.0, max_value=100.0)

    assert repr(float_obj1) == str(float_obj1) == "Float(required=True)"
    assert repr(float_obj2) == str(float_obj2) == "Float(required=True, default=100.0)"
    assert (
        repr(float_obj3)
        == str(float_obj3)
        == "Float(required=True, max_value=100.0, min_value=0.0)"
    )
    assert (
        repr(float_obj4)
        == str(float_obj4)
        == "Float(required=True, default=100.0, max_value=100.0, min_value=0.0)"
    )


def test_auto_repr_and_str():
    auto_obj1 = Auto()
    auto_obj2 = Auto(required=True, increment=True)

    assert repr(auto_obj1) == str(auto_obj1) == "Auto()"
    assert repr(auto_obj2) == str(auto_obj2) == "Auto(increment=True)"
