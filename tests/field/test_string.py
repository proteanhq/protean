from protean.fields import String


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
