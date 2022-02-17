from typing import TYPE_CHECKING, Dict

from protean.port.broker import BaseBroker
from protean.utils import fully_qualified_name
from protean.utils.mixins import Message

if TYPE_CHECKING:
    from protean.domain import Domain


class InlineBroker(BaseBroker):
    def __init__(self, name: str, domain: "Domain", conn_info: Dict[str, str]) -> None:
        super().__init__(name, domain, conn_info)

        # In case of `InlineBroker`, the `IS_ASYNC` value will always be `False`.
        conn_info["IS_ASYNC"] = False

    def publish(self, message: Message) -> None:
        initiator_obj = message.to_object()

        for subscriber in self._subscribers[
            fully_qualified_name(initiator_obj.__class__)
        ]:
            subscriber()(message.data)

    def get_next(self) -> Dict:
        """No-Op"""
        return None

    def _data_reset(self) -> None:
        """No-Op"""
