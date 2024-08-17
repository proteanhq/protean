import pytest

from protean.utils.container import Options


@pytest.fixture
def opts_dict():
    return {"opt1": "value1", "opt2": "value2", "abstract": True}


@pytest.fixture
def opts_object():
    return Options({"opt1": "value1", "opt2": "value2", "abstract": True})


def test_options_initialization(opts_dict, opts_object):
    # Test initialization with a dictionary
    options = Options(opts_dict)
    assert options.opt1 == "value1"
    assert options.opt2 == "value2"
    assert options.abstract is True

    # Test initialization with an Options object
    options = Options(opts_object)
    assert options.opt1 == "value1"
    assert options.opt2 == "value2"
    assert options.abstract is True

    # Test initialization with None
    options = Options()
    assert options.abstract is False

    # Test initialization with an invalid type
    with pytest.raises(ValueError):
        Options("invalid")  # type: ignore  - This is expected to raise an exception


def test_attribute_access_and_modification(opts_dict):
    options = Options(opts_dict)

    # Test getattr
    assert options.opt1 == "value1"

    # Test setattr
    options.opt3 = "value3"
    assert options.opt3 == "value3"
    assert "opt3" in options

    # Test delattr
    del options.opt1
    assert not hasattr(options, "opt1")
    assert "opt1" not in options


def test_options_equality(opts_dict):
    # Test equality
    options1 = Options(opts_dict)
    options2 = Options(opts_dict)
    assert options1 == options2

    # Test inequality with different values
    options2 = Options({"opt1": "value1", "opt2": "different_value", "abstract": True})
    assert options1 != options2


def test_merging_options(opts_dict):
    options1 = Options(opts_dict)
    options2 = Options({"opt3": "value3"})

    # Test merging options
    merged_options = options1 + options2
    assert merged_options.opt1 == "value1"
    assert merged_options.opt2 == "value2"
    assert merged_options.opt3 == "value3"
    assert merged_options.abstract is False

    # Test that original options are not modified
    assert not hasattr(options1, "opt3")


def test_tracking_keys(opts_dict):
    options = Options({"foo": "bar"})
    assert set(options.keys()) == {"abstract", "foo"}

    setattr(options, "baz", "qux")
    assert set(options.keys()) == {"abstract", "foo", "baz"}

    options.waldo = "fred"
    assert set(options.keys()) == {"abstract", "foo", "baz", "waldo"}

    del options.baz
    assert set(options.keys()) == {"abstract", "foo", "waldo"}
