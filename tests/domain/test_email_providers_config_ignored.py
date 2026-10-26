"""The email port is removed, and an ``[email_providers]`` block is ignored."""

import importlib
import warnings

import pytest

import protean.adapters
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

    def test_registry_has_no_emails_accessor(self):
        domain = Domain(name="NoEmail")

        with pytest.raises(AttributeError):
            domain.registry.emails

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

    @pytest.mark.parametrize("module", ["protean.core.email", "protean.adapters.email"])
    def test_email_modules_are_gone(self, module):
        with pytest.raises(ImportError):
            importlib.import_module(module)

    @pytest.mark.parametrize("name", ["EmailProviders", "DummyEmailProvider"])
    def test_adapters_package_does_not_export_email_providers(self, name):
        assert not hasattr(protean.adapters, name)
