import pytest


@pytest.fixture(scope="module", autouse=True)
def _release_mypy_build():
    """Drop the last in-process mypy build once a module's tests are done.

    ``mypy.api.run`` leaves the modules of its last build in the global
    ``mypy.modules_state.modules_state``. That is over a million objects the
    rest of the session never uses but still keeps alive, and every later
    garbage collection has to walk them.
    """
    yield

    try:
        from mypy.modules_state import modules_state
    except ImportError:
        return
    modules_state.modules = {}
    modules_state.node_fixer = None
