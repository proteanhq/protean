import importlib
import logging
from typing import TYPE_CHECKING

from protean.exceptions import ConfigurationError

if TYPE_CHECKING:
    from protean.core.email import BaseEmail, BaseEmailProvider
    from protean.domain import Domain

logger = logging.getLogger(__name__)


class EmailProviders:
    def __init__(self, domain: "Domain") -> None:
        self.domain = domain
        self._email_providers: dict[str, BaseEmailProvider] | None = None

    def _initialize_email_providers(self) -> None:
        """Read config file and initialize email providers"""
        configured_email_providers = self.domain.config["email_providers"]
        email_provider_objects: dict[str, BaseEmailProvider] = {}

        if configured_email_providers and isinstance(configured_email_providers, dict):
            if "default" not in configured_email_providers:
                raise ConfigurationError("You must define a 'default' email provider")

            for provider_name, conn_info in configured_email_providers.items():
                provider_full_path = conn_info["provider"]
                provider_module, provider_class = provider_full_path.rsplit(
                    ".", maxsplit=1
                )

                provider_cls = getattr(
                    importlib.import_module(provider_module), provider_class
                )
                email_provider_objects[provider_name] = provider_cls(
                    provider_name, self, conn_info
                )

        self._email_providers = email_provider_objects

    def get_email_provider(self, provider_name: str) -> "BaseEmailProvider":
        """Retrieve the email provider object with a given provider name"""
        if self._email_providers is None:
            self._initialize_email_providers()

        try:
            assert self._email_providers is not None
            return self._email_providers[provider_name]
        except KeyError as exc:
            raise AssertionError(
                f"No Provider registered with name {provider_name}"
            ) from exc

    def send_email(self, email: "BaseEmail") -> None:
        """Push email through registered provider"""
        if self._email_providers is None:
            self._initialize_email_providers()

        logger.debug(f"Pushing {email.__class__.__name__} with content {email!r}")
        assert self._email_providers is not None
        self._email_providers[email.meta_.provider].send_email(email)
