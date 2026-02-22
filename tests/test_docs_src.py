import importlib
import os
import sys

from protean import current_domain

# Build the path to the module with a hyphenated directory name
_docs_src = os.path.abspath(os.path.join(os.path.dirname(__file__), "../docs_src"))
_spec = importlib.util.spec_from_file_location(
    "change_state_008",
    os.path.join(_docs_src, "guides", "change-state", "008.py"),
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

auth = _mod.auth
User = _mod.User
UserApplicationServices = _mod.UserApplicationServices


def test_import_my_module():
    try:
        assert auth is not None
        assert User is not None
        assert UserApplicationServices is not None

        assert True  # If the import succeeds, the test passes
    except ImportError:
        assert False, "Module in docs_src could not be imported"


def test_application_service_method_invocation():
    with auth.domain_context():
        # Run a sample test from elements declared in docs_src
        app_services_obj = UserApplicationServices()

        user_id = app_services_obj.register_user(
            email="john.doe@gmail.com", name="John Doe"
        )
        assert user_id is not None

        app_services_obj.activate_user(user_id)
        user = current_domain.repository_for(User).get(user_id)
        assert user.status == "ACTIVE"
