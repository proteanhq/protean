import pytest

from protean.utils.container import Options


@pytest.fixture
def opts_dict():
    return {"opt1": "value1", "opt2": "value2", "abstract": True}


@pytest.fixture
def opts_object():
    return Options({"opt1": "value1", "opt2": "value2", "abstract": True})


def test_init_with_dict(opts_dict):
    options = Options(opts_dict)
    assert options.opt1 == "value1"
    assert options.opt2 == "value2"
    assert options.abstract is True


def test_init_with_class(opts_object):
    options = Options(opts_object)
    assert options.opt1 == "value1"
    assert options.opt2 == "value2"
    assert options.abstract is True


def test_init_with_none():
    options = Options()
    assert options.abstract is False


def test_init_with_invalid_type():
    with pytest.raises(ValueError):
        Options("invalid")


def test_setattr_and_getattr(opts_dict):
    options = Options(opts_dict)
    options.opt3 = "value3"
    assert options.opt3 == "value3"
    assert "opt3" in options._opts


def test_delattr(opts_dict):
    options = Options(opts_dict)
    del options.opt1
    assert not hasattr(options, "opt1")
    assert "opt1" not in options._opts


def test_eq(opts_dict):
    options1 = Options(opts_dict)
    options2 = Options(opts_dict)
    assert options1 == options2


def test_ne(opts_dict):
    options1 = Options(opts_dict)
    options2 = Options({"opt1": "value1", "opt2": "different_value", "abstract": True})
    assert options1 != options2


def test_ne_different_type(opts_dict):
    class NotOptions(Options):
        pass

    options = Options(opts_dict)
    not_options = NotOptions(opts_dict)
    assert options != not_options


def test_hash(opts_dict):
    options = Options(opts_dict)
    assert isinstance(hash(options), int)


def test_add(opts_dict):
    options1 = Options(opts_dict)
    options2 = Options({"opt3": "value3"})
    options3 = options1 + options2
    assert options3.opt1 == "value1"
    assert options3.opt2 == "value2"
    assert options3.opt3 == "value3"
    assert options3.abstract is False


def test_add_does_not_modify_original(opts_dict):
    options1 = Options(opts_dict)
    options2 = Options({"opt3": "value3"})
    options1 + options2
    assert not hasattr(options1, "opt3")
