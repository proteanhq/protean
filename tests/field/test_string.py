from protean.fields import String


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


def test_sanitization_option_for_string_fields():
    str_field1 = String()
    assert str_field1.sanitize is True

    str_field1 = String(sanitize=False)
    assert str_field1.sanitize is False


def test_that_string_values_are_automatically_cleaned():
    str_field = String()

    value = str_field._load("an <script>evil()</script> example")
    assert value == "an &lt;script&gt;evil()&lt;/script&gt; example"


def test_that_sanitization_can_be_optionally_switched_off():
    str_field = String(sanitize=False)

    value = str_field._load("an <script>evil()</script> example")
    assert value == "an <script>evil()</script> example"
