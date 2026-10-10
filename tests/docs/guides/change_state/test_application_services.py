"""Check what docs/guides/change-state/application-services.md says.

Each test loads its example fresh, so every test gets its own domain and its
own memory store. ``008.py`` initializes its own ``auth`` domain; the other
examples are initialized here.
"""

import re
import subprocess
import sys

import pytest

from protean.exceptions import ObjectNotFoundError, ValidationError
from tests.docs.support import DOCS_SRC, REPO_ROOT, load_example

pytestmark = pytest.mark.no_test_domain


@pytest.fixture
def auth_example():
    module = load_example("guides/change-state/008.py")
    with module.auth.domain_context():
        yield module


def activated(module):
    module.domain.init(traverse=False)
    return module.domain.domain_context()


@pytest.fixture
def order_example():
    module = load_example("guides/change-state/application-services/001.py")
    with activated(module):
        yield module


@pytest.fixture
def return_values_example():
    module = load_example("guides/change-state/application-services/002.py")
    with activated(module):
        yield module


@pytest.fixture
def errors_example():
    module = load_example("guides/change-state/application-services/003.py")
    with activated(module):
        yield module


class TestDefiningAnApplicationService:
    def test_register_user_returns_the_id_of_an_inactive_user(self, auth_example):
        user_id = auth_example.UserApplicationServices().register_user(
            email="jane@example.com", name="Jane Doe"
        )

        user = auth_example.auth.repository_for(auth_example.User).get(user_id)
        assert user.id == user_id
        assert user.email == "jane@example.com"
        assert user.name == "Jane Doe"
        assert user.status == "INACTIVE"

    def test_calling_the_service_directly_leaves_an_active_user(self, auth_example):
        user_id = auth_example.register_and_activate()

        user = auth_example.auth.repository_for(auth_example.User).get(user_id)
        assert user.email == "john@example.com"
        assert user.name == "John Doe"
        assert user.status == "ACTIVE"


class TestUseCaseDecorator:
    def test_place_order_returns_the_id_of_the_saved_order(self, order_example):
        order_id = order_example.OrderApplicationServices().place_order(
            customer_id="cust-1", items=["book", "pen"]
        )

        order = order_example.domain.repository_for(order_example.Order).get(order_id)
        assert order.customer_id == "cust-1"
        assert order.items == ["book", "pen"]

    def test_place_order_that_fails_saves_nothing(self, order_example):
        repo = order_example.domain.repository_for(order_example.Order)
        service = order_example.OrderApplicationServices()
        saved_id = service.place_order(customer_id="cust-1", items=["book"])

        # customer_id is required, so Order.create raises inside the use case.
        with pytest.raises(ValidationError) as exc_info:
            service.place_order(customer_id=None, items=["pen"])

        assert "customer_id" in exc_info.value.messages
        orders = repo.query.all().items
        assert [order.id for order in orders] == [saved_id]


class TestReturnValues:
    def test_each_use_case_returns_what_the_page_shows(self, return_values_example):
        service = return_values_example.UserApplicationServices()

        user_id = service.register_user(email="john@example.com", name="John Doe")
        assert service.activate_user(user_id) is None
        user = service.get_user(user_id)

        assert isinstance(user, return_values_example.User)
        assert user.id == user_id
        assert user.email == "john@example.com"
        assert user.status == "ACTIVE"

    def test_get_user_raises_for_an_unknown_id(self, return_values_example):
        service = return_values_example.UserApplicationServices()
        known_id = service.register_user(email="john@example.com", name="John Doe")
        assert service.get_user(known_id).name == "John Doe"

        with pytest.raises(ObjectNotFoundError):
            service.get_user("no-such-user")


class TestErrorHandling:
    def test_the_api_layer_gets_the_new_user_id(self, errors_example):
        user_id = errors_example.register_john()

        user = errors_example.domain.repository_for(errors_example.User).get(user_id)
        assert user.email == "john@example.com"
        assert user.name == "John Doe"

    def test_a_validation_error_reaches_the_caller(self, errors_example):
        service = errors_example.UserApplicationServices()
        service.register_user(email="john@example.com", name="John Doe")

        # The email is unique, so saving a second John fails.
        with pytest.raises(ValidationError) as exc_info:
            service.register_user(email="john@example.com", name="Johnny")

        assert "email" in exc_info.value.messages

    def test_the_api_layer_catches_the_error_and_nothing_new_is_saved(
        self, errors_example
    ):
        first_id = errors_example.register_john()

        assert errors_example.register_john() is None

        users = errors_example.domain.repository_for(errors_example.User).query.all()
        assert [(user.id, user.name) for user in users.items] == [
            (first_id, "John Doe")
        ]


class TestTestingApplicationServices:
    def test_page_test_passes_under_pytest(self):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                str(DOCS_SRC / "guides/change-state/application-services/002.py"),
                "-p",
                "no:cacheprovider",
                "-p",
                "no:randomly",
                "-q",
                "--import-mode=importlib",
                "-W",
                "error::pytest.PytestCollectionWarning",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            check=False,
            text=True,
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert re.search(r"\b1 passed\b", result.stdout), result.stdout
