from protean.container import Options


class Meta:
    foo = "bar"


def test_options_construction_from_meta_class():
    opts = Options(Meta)

    assert opts is not None
    assert opts.foo == "bar"


def test_options_construction_from_dict():
    opts = Options({"foo": "bar"})

    assert opts is not None
    assert opts.foo == "bar"


def test_option_objects_equality():
    assert Options() == Options()
    assert Options(Meta) == Options({"foo": "bar"})

    assert Options({"foo": "bar"}) == Options({"foo": "bar"})
    assert Options({"foo": "bar"}) != Options({"foo": "baz"})

    class Meta2:
        foo = "bar"

    assert Options(Meta) == Options(Meta2)

    class Meta3:
        foo = "baz"

    assert Options(Meta) != Options(Meta3)
