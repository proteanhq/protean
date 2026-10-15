# --8<-- [start:steps]
# tests/bdd/registration/test_register_user.py
from uuid import uuid4

from myapp import domain
from myapp.commands import Register
from myapp.models import Notification, User
from pytest_bdd import given, parsers, scenarios, then, when

from protean.exceptions import ValidationError

scenarios("features/register_user.feature")


@when(
    parsers.parse('a Register command is processed for "{email}"'),
    target_fixture="email",
)
def process_register(email):
    domain.process(Register(user_id=str(uuid4()), email=email, name="Test User"))
    return email


@then(parsers.parse('a user should exist with email "{email}"'))
def user_exists(email):
    users = domain.repository_for(User).query.all()
    match = [u for u in users.items if u.email == email]
    assert len(match) == 1


@then(parsers.parse('the user status should be "{status}"'))
def user_has_status(email, status):
    users = domain.repository_for(User).query.all()
    user = next(u for u in users.items if u.email == email)
    assert user.status == status


@then(parsers.parse('a welcome notification should have been sent to "{email}"'))
def welcome_sent(email):
    sent = domain.repository_for(Notification).query.filter(recipient=email).all()
    assert [n.kind for n in sent.items] == ["welcome"]


@given(parsers.parse('a user already exists with email "{email}"'))
def user_already_exists(email):
    domain.process(Register(user_id=str(uuid4()), email=email, name="First User"))


@when(
    parsers.parse('a Register command is attempted for "{email}"'),
    target_fixture="registration_result",
)
def attempt_register(email):
    try:
        domain.process(Register(user_id=str(uuid4()), email=email, name="Test User"))
        return {"success": True}
    except ValidationError as exc:
        return {"success": False, "error": str(exc.messages)}


@then(parsers.parse('the command should fail with error "{message}"'))
def registration_failed(registration_result, message):
    assert registration_result["success"] is False
    assert message in registration_result["error"]
    assert domain.repository_for(User).query.all().total == 1


# --8<-- [end:steps]
