# --8<-- [start:tests]
import pytest

from protean import Domain


def test_runs_inside_the_conformance_domain(test_domain):
    assert test_domain.name == "AdapterConformanceTest"


@pytest.mark.no_test_domain
def test_builds_its_own_domain(test_domain):
    assert test_domain is None  # the autouse fixture stepped aside

    domain = Domain(name="Test")
    domain.init(traverse=False)
    with domain.domain_context():
        assert domain.name == "Test"


# --8<-- [end:tests]

# Each test keeps the domain it was given, so whichever runs second fails if
# the fixture handed out the same instance twice.
seen_domains = []


@pytest.mark.parametrize("run", [1, 2])
def test_each_test_gets_a_fresh_initialized_domain(test_domain, run):
    assert test_domain.providers["default"].conn_info["provider"] == "memory"
    assert all(earlier is not test_domain for earlier in seen_domains)
    seen_domains.append(test_domain)
