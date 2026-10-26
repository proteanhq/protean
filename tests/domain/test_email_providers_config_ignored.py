"""The email port is removed, and an ``[email_providers]`` block is ignored."""

import importlib
import inspect
import tomllib
import warnings
from pathlib import Path

import pytest

import protean
import protean.adapters
import protean.domain.registry
from protean._deprecation import DEPRECATIONS, ProteanDeprecationWarning
from protean.domain import Domain
from protean.fields import String
from protean.ir.diagnostics import DiagnosticCode
from protean.utils import DomainObjects

pytestmark = pytest.mark.no_test_domain

EMAIL_PROVIDERS_TOML = """\
snapshot_threshold = 42

[email_providers.default]
provider = "protean.adapters.DummyEmailProvider"
DEFAULT_FROM_EMAIL = "admin@example.com"
"""


@pytest.fixture
def domain_with_email_providers_block(tmp_path):
    (tmp_path / "domain.toml").write_text(EMAIL_PROVIDERS_TOML)
    return tmp_path


class TestEmailProvidersConfigIsIgnored:
    def test_the_block_is_dropped_from_the_loaded_config(
        self, domain_with_email_providers_block
    ):
        domain = Domain(
            name="EmailCfg", root_path=str(domain_with_email_providers_block)
        )

        # The known key proves the file was loaded, so the missing block is
        # the result of the block being dropped, not of a file never read.
        assert domain.config["snapshot_threshold"] == 42
        assert "email_providers" not in domain.config

    def test_init_completes_without_a_deprecation_warning(
        self, domain_with_email_providers_block
    ):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")

            domain = Domain(
                name="EmailCfg", root_path=str(domain_with_email_providers_block)
            )

            @domain.aggregate
            class Order:
                name = String(max_length=50)

            domain.init(traverse=False)

        assert [
            w for w in caught if issubclass(w.category, ProteanDeprecationWarning)
        ] == []


class TestEmailPortIsRemoved:
    @pytest.mark.parametrize("name", ["email", "send_email", "get_email_provider"])
    def test_domain_has_no_email_api(self, name):
        domain = Domain(name="NoEmail")

        with pytest.raises(AttributeError):
            getattr(domain, name)

    def test_registry_declares_no_emails_accessor(self):
        # The accessor annotations sit in a ``TYPE_CHECKING`` block that never
        # runs, so only the source shows whether ``emails`` is still declared.
        source = inspect.getsource(protean.domain.registry)

        assert "aggregates: dict[str, DomainRecord]" in source
        assert "emails:" not in source

    def test_email_is_not_an_element_type(self):
        assert "EMAIL" not in DomainObjects.__members__

    @pytest.mark.parametrize("code", ["DEPRECATED_EMAIL", "DEPRECATED_CONFIG"])
    def test_check_has_no_email_codes(self, code):
        assert code not in DiagnosticCode.__members__

    def test_no_email_deprecation_is_registered(self):
        assert DEPRECATIONS
        assert {
            "email_element",
            "email_providers_config",
            "get_email_provider",
            "send_email",
        }.isdisjoint(DEPRECATIONS)

    # A checkout that moved past the removal can keep an untracked
    # ``__pycache__`` directory, which imports as an empty namespace package,
    # so the check looks for a name the module used to define.
    @pytest.mark.parametrize(
        "module, name",
        [
            ("protean.core.email", "BaseEmail"),
            ("protean.adapters.email", "EmailProviders"),
        ],
    )
    def test_email_modules_are_gone(self, module, name):
        try:
            imported = importlib.import_module(module)
        except ImportError:
            return

        assert not hasattr(imported, name)

    @pytest.mark.parametrize("name", ["EmailProviders", "DummyEmailProvider"])
    def test_adapters_package_does_not_export_email_providers(self, name):
        assert not hasattr(protean.adapters, name)


def _pyproject_path() -> Path:
    path = Path(protean.__file__).resolve().parents[2] / "pyproject.toml"
    if not path.exists():
        pytest.skip("pyproject.toml not available (installed, non-editable)")
    return path


class TestSendgridPackagingIsRemoved:
    def test_there_is_no_sendgrid_extra(self):
        pyproject = tomllib.loads(_pyproject_path().read_text(encoding="utf-8"))
        extras = pyproject["project"]["optional-dependencies"]

        assert extras
        assert "sendgrid" not in extras

    def test_there_is_no_sendgrid_pytest_marker(self):
        pyproject = tomllib.loads(_pyproject_path().read_text(encoding="utf-8"))
        markers = pyproject["tool"]["pytest"]["ini_options"]["markers"]

        assert markers
        assert [m for m in markers if m.split(":")[0].strip() == "sendgrid"] == []

    def test_the_lock_has_no_sendgrid_package(self):
        lock_path = _pyproject_path().with_name("uv.lock")
        if not lock_path.exists():
            pytest.skip("uv.lock not available")
        packages = tomllib.loads(lock_path.read_text(encoding="utf-8"))["package"]

        assert packages
        assert "sendgrid" not in {p["name"] for p in packages}
