import pytest

from tests.shared import initialize_domain


@pytest.fixture(autouse=True)
def test_domain(request):
    if "no_test_domain" in request.keywords:
        yield
    else:
        domain = initialize_domain(name="Observatory Tests", root_path=__file__)
        domain.init(traverse=False)

        with domain.domain_context():
            yield domain
