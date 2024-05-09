from protean.fields import Text


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
