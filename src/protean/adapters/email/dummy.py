"""A Dummy Email Provider class"""
import logging

from protean.core.email import BaseEmailProvider

logger = logging.getLogger("protean.adapters.email")


class DummyEmailProvider(BaseEmailProvider):
    """
    An email backend to simulate Email messages
    """

    def __init__(self, name, domain, conn_info):
        super().__init__(name, domain, conn_info)

    def send_email(self, message, dynamic_template=False):
        """Output message into log"""

        logger.debug("Email message dispatched: %s" % message)
        return True
