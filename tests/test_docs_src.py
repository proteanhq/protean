from guides.change_state_008 import User, UserApplicationServices

from protean import current_domain


def test_import_my_module():
    try:
        from guides.change_state_008 import (
            Registered,
            User,
            UserApplicationServices,
            auth,
        )

        assert True  # If the import succeeds, the test passes
    except ImportError:
        assert False, "Module in docs_src could not be imported"


def test_application_service_method_invocation():
    # Run a sample test from elements declared in docs_src
    app_services_obj = UserApplicationServices()

    user_id = app_services_obj.register_user(
        email="john.doe@gmail.com", name="John Doe"
    )
    assert user_id is not None

    app_services_obj.activate_user(user_id)
    user = current_domain.repository_for(User).get(user_id)
    assert user.status == "ACTIVE"
