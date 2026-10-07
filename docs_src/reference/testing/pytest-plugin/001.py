# --8<-- [start:opt_in]
pytest_plugins = ["protean.integrations.pytest.adapter_conformance"]
# --8<-- [end:opt_in]

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
