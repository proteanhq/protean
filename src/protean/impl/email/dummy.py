"""A Dummy Email Provider class"""
import logging

from protean.core.email import BaseEmailProvider

logger = logging.getLogger('protean.impl.email')


class DummyEmailProvider(BaseEmailProvider):
    """
    An email backend to simulate Email messages
    """

    def send_email(self, messages, dynamic_template=False):
        """Output message into log"""

        msg_count = 0
        for message in messages:
            logger.info('Email message dispatched: %s' % message.mime_message())
            msg_count += 1

        return msg_count
