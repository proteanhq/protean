from protean.fields import Nested


def test_nested_field_repr_and_str():
    nested_obj1 = Nested("schema1")
    nested_obj2 = Nested("schema1", many=True, required=True)
    nested_obj3 = Nested("schema1", default={"name": "John Doe"})
    nested_obj4 = Nested("schema1", required=True, default={"name": "John Doe"})

    assert repr(nested_obj1) == str(nested_obj1) == "Nested('schema1')"
    assert repr(nested_obj2) == str(nested_obj2) == "Nested('schema1', required=True)"
    assert (
        repr(nested_obj3)
        == str(nested_obj3)
        == "Nested('schema1', default={'name': 'John Doe'})"
    )
    assert (
        repr(nested_obj4)
        == str(nested_obj4)
        == "Nested('schema1', required=True, default={'name': 'John Doe'})"
    )
