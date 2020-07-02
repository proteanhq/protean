"""A Dummy Email Provider class"""
# Standard Library Imports
import logging

# Protean
from protean.core.email import BaseEmailProvider

logger = logging.getLogger("protean.impl.email")


class DummyEmailProvider(BaseEmailProvider):
    """
    An email backend to simulate Email messages
    """

    def __init__(self, name, domain, conn_info):
        super().__init__(name, domain, conn_info)

    def send_email(self, message, dynamic_template=False):
        """Output message into log"""

        logger.debug("Email message dispatched: %s" % message.mime_message)
        return True
