import importlib

from protean.utils import get_version


def test_get_version():
    assert get_version() == importlib.metadata.version("protean")
