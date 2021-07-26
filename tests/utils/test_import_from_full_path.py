import pytest

from protean.utils.importlib import import_from_full_path


def test_that_a_domain_can_be_imported_from_a_full_path():
    domain = import_from_full_path("publishing", "tests/utils/support/domain.py")

    assert domain is not None
    assert domain.domain_name == "Publishing Domain"


def test_that_an_invalid_file_path_throws_exception():
    with pytest.raises(FileNotFoundError):
        import_from_full_path("publishing", "dummy_path/domain.py")
