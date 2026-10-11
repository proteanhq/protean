import pytest

from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def test_application_service_method_invocation():
    example = load_example("guides/change-state/008.py")

    with example.auth.domain_context():
        service = example.UserApplicationServices()

        user_id = service.register_user(email="john.doe@gmail.com", name="John Doe")
        assert user_id is not None

        service.activate_user(user_id)
        user = example.auth.repository_for(example.User).get(user_id)
        assert user.status == "ACTIVE"
