"""The Flask example on the FastAPI integration guide behaves as the page says."""

import pytest

from protean.domain.context import has_domain_context
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def test_the_flask_hooks_push_the_context_per_request_and_pop_it_after():
    example = load_example("guides/fastapi/index/010.py")
    client = example.app.test_client()

    response = client.get("/whoami")

    assert response.json == {"domain": "Ordering"}
    assert not has_domain_context()
