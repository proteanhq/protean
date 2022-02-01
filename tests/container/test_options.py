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


def test_tracking_currently_active_attributes():
    opts = Options({"foo": "bar"})
    assert opts._opts == {"abstract", "foo"}

    setattr(opts, "baz", "qux")
    assert opts._opts == {"abstract", "foo", "baz"}

    opts.waldo = "fred"
    assert opts._opts == {"abstract", "foo", "baz", "waldo"}

    del opts.baz
    assert opts._opts == {"abstract", "foo", "waldo"}


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


def test_merging_two_option_objects():
    opt1 = Options({"foo": "bar", "baz": "qux"})
    opt2 = Options({"baz": "quz"})

    merged1 = opt1 + opt2
    assert merged1.baz == "quz"

    merged2 = opt2 + opt1
    assert merged2.baz == "qux"
