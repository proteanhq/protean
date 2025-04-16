from protean.fields.basic import String

def test_deprecated_flag_is_set_correctly():
    field = String(deprecated=True)
    assert field.deprecated is True

def test_deprecated_flag_default_is_false():
    field = String()
    assert field.deprecated is False
