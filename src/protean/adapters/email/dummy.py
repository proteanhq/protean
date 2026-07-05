"""A Dummy Email Provider class"""

import logging
from typing import TYPE_CHECKING, Any

from protean.core.email import BaseEmailProvider

if TYPE_CHECKING:
    from protean.core.email import BaseEmail

logger = logging.getLogger(__name__)


class DummyEmailProvider(BaseEmailProvider):
    """
    An email backend to simulate Email messages
    """

    def __init__(self, name: str, domain: Any, conn_info: dict[str, Any]) -> None:
        super().__init__(name, domain, conn_info)

    def send_email(self, email_message: "BaseEmail") -> bool:
        """Output message into log"""

        logger.debug("Email message dispatched: %s" % email_message)
        return True
