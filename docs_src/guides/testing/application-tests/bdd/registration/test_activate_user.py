# --8<-- [start:steps]
# tests/bdd/registration/test_activate_user.py
from myapp import domain
from myapp.models import User
from myapp.services import UserApplicationServices
from pytest_bdd import given, parsers, scenarios, then, when

from protean.exceptions import ObjectNotFoundError

scenarios("features/activate_user.feature")


@given(
    parsers.parse('a registered user "{email}"'),
    target_fixture="user_id",
)
def registered_user(email):
    app_service = UserApplicationServices()
    return app_service.register_user(email=email, name="Test User")


@when("the user is activated")
def activate_user(user_id):
    app_service = UserApplicationServices()
    app_service.activate_user(user_id)


@when(
    "activation is attempted for a non-existent user",
    target_fixture="activation_result",
)
def activate_nonexistent():
    try:
        app_service = UserApplicationServices()
        app_service.activate_user("nonexistent-id")
        return {"success": True}
    except ObjectNotFoundError as exc:
        return {"success": False, "error": str(exc)}


@then(parsers.parse('the user status should be "{status}"'))
def check_status(user_id, status):
    user = domain.repository_for(User).get(user_id)
    assert user.status == status


@then(parsers.parse('the operation should fail with "{message}"'))
def check_failure(activation_result, message):
    assert activation_result["success"] is False
    assert message in activation_result["error"]


# --8<-- [end:steps]
