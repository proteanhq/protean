import pkg_resources

from protean.utils import get_version


def test_get_version():
    assert get_version() == pkg_resources.require("protean")[0].version
