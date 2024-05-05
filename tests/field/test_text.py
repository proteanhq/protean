from protean.fields import Text


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


def test_sanitization_option_for_text_fields():
    text_field1 = Text()
    assert text_field1.sanitize is True

    text_field1 = Text(sanitize=False)
    assert text_field1.sanitize is False


def test_that_text_values_are_automatically_cleaned():
    text_field = Text()

    value = text_field._load("an <script>evil()</script> example")
    assert value == "an &lt;script&gt;evil()&lt;/script&gt; example"


def test_that_sanitization_can_be_optionally_switched_off():
    text_field = Text(sanitize=False)

    value = text_field._load("an <script>evil()</script> example")
    assert value == "an <script>evil()</script> example"
