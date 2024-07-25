import importlib
import logging

from protean.exceptions import ConfigurationError

logger = logging.getLogger(__name__)


class EmailProviders:
    def __init__(self, domain):
        self.domain = domain
        self._email_providers = None

    def _initialize_email_providers(self):
        """Read config file and initialize email providers"""
        configured_email_providers = self.domain.config["email_providers"]
        email_provider_objects = {}

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

    def get_email_provider(self, provider_name):
        """Retrieve the email provider object with a given provider name"""
        if self._email_providers is None:
            self._initialize_email_providers()

        try:
            return self._email_providers[provider_name]
        except KeyError:
            raise AssertionError(f"No Provider registered with name {provider_name}")

    def send_email(self, email):
        """Push email through registered provider"""
        if self._email_providers is None:
            self._initialize_email_providers()

        logger.debug(f"Pushing {email.__class__.__name__} with content {repr(email)}")
        self._email_providers[email.meta_.provider].send_email(email)
