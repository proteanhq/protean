"""The FastAPI integration reports an install hint when fastapi is absent (ADR-0029).

``fastapi`` ships in the optional ``protean[server]`` extra. Importing
``protean.integrations.fastapi`` without it must fail with a message naming the
extra, not a bare ``ModuleNotFoundError`` from deep inside the package. An
import error from a fastapi that is installed surfaces unchanged.
"""

import importlib

import pytest

from tests.shared import module_unavailable

pytestmark = pytest.mark.no_test_domain


def test_importing_integration_without_fastapi_reports_actionable_error():
    with module_unavailable("fastapi", reload=("protean.integrations.fastapi",)):
        with pytest.raises(ImportError) as exc_info:
            importlib.import_module("protean.integrations.fastapi")

    message = str(exc_info.value)
    assert "protean.integrations.fastapi" in message
    assert 'pip install "protean[server]"' in message


def test_import_error_from_an_installed_fastapi_is_raised_unchanged():
    # fastapi is installed, but one of its submodules fails to import, so the
    # original error surfaces instead of an install hint.
    with module_unavailable(
        "fastapi.responses", reload=("protean.integrations.fastapi",)
    ):
        with pytest.raises(ImportError) as exc_info:
            importlib.import_module("protean.integrations.fastapi")

    assert exc_info.value.name == "fastapi.responses"
    assert "pip install" not in str(exc_info.value)


def test_integration_imports_normally_when_fastapi_is_present():
    # Sanity check that the guard does not interfere with the happy path.
    module = importlib.import_module("protean.integrations.fastapi")

    assert hasattr(module, "DomainContextMiddleware")
    assert hasattr(module, "create_health_router")
