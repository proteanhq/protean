from unittest.mock import MagicMock

import pytest

from protean import Domain
from protean.cli import NoDomainException
from protean.utils.domain_discovery import find_domain_by_string


class MagicMockWithName(MagicMock):
    __name__ = "mock_module"


@pytest.fixture
def mock_module():
    module = MagicMockWithName()

    # Configure the module for different test scenarios
    module.valid_domain = Domain(__file__, load_toml=False)
    module.not_a_domain = "not a domain instance"
    return module


def test_find_domain_by_string_with_empty_domain_name(mock_module):
    with pytest.raises(NoDomainException) as exc_info:
        find_domain_by_string(mock_module, "")
    assert "Failed to parse" in str(
        exc_info.value
    ), "Should raise exception for empty domain name"


def test_find_domain_by_string_with_whitespace_domain_name(mock_module):
    mock_module.valid_domain = Domain(__file__, load_toml=False)
    domain = find_domain_by_string(mock_module, " valid_domain ")
    assert isinstance(
        domain, Domain
    ), "Should correctly ignore leading/trailing whitespace"


def test_find_domain_by_string_with_none_as_domain(mock_module):
    mock_module.none_domain = None  # Set a None domain
    with pytest.raises(NoDomainException) as exc_info:
        find_domain_by_string(mock_module, "none_domain")
    assert "A valid Protean domain was not obtained" in str(
        exc_info.value
    ), "Should raise exception when the domain is None"


def test_find_domain_by_string_with_valid_domain(mock_module):
    domain = find_domain_by_string(mock_module, "valid_domain")
    assert isinstance(domain, Domain), "Should return a Domain instance"


def test_find_domain_by_string_with_non_domain(mock_module):
    with pytest.raises(NoDomainException) as exc_info:
        find_domain_by_string(mock_module, "not_a_domain")
    assert "A valid Protean domain was not obtained" in str(exc_info.value)


def test_find_domain_by_string_with_invalid_syntax():
    with pytest.raises(NoDomainException) as exc_info:
        find_domain_by_string(None, "invalid syntax!")
    assert "Failed to parse" in str(exc_info.value)


def test_find_domain_by_string_with_nonexistent_attribute(mock_module):
    with pytest.raises(NoDomainException) as exc_info:
        find_domain_by_string(mock_module, "nonexistent")
    assert "A valid Protean domain was not obtained from " in str(exc_info.value)


def test_find_domain_by_string_with_function_call(mock_module):
    mock_module.domain_function = MagicMock(
        return_value=Domain(__file__, load_toml=False)
    )
    domain = find_domain_by_string(mock_module, "domain_function()")
    assert isinstance(domain, Domain), "Should handle function calls correctly"


def test_find_domain_by_string_with_function_call_with_arguments(mock_module):
    with pytest.raises(NoDomainException) as exc_info:
        find_domain_by_string(mock_module, "domain_function(arg1, arg2)")
    assert "Function calls with arguments are not supported" in str(
        exc_info.value
    ), "Should raise exception for function calls with arguments"


def test_find_domain_by_string_returns_correct_domain_instance(mock_module):
    expected_domain = Domain(__file__, load_toml=False)
    mock_module.specific_domain = expected_domain
    actual_domain = find_domain_by_string(mock_module, "specific_domain")
    assert (
        actual_domain is expected_domain
    ), "Should return the specific Domain instance associated with 'specific_domain'"
