from typing import Dict
from protean.globals import current_domain
from protean.infra.eventing import Message
from protean.port.broker import BaseBroker
from protean.utils import fully_qualified_name

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from protean.domain import Domain


class InlineBroker(BaseBroker):
    def __init__(self, name: str, domain: "Domain", conn_info: Dict[str, str]) -> None:
        super().__init__(name, domain, conn_info)

        # In case of `InlineBroker`, the `IS_ASYNC` value will always be `False`.
        conn_info["IS_ASYNC"] = False

    def publish(self, message: Message) -> None:
        # FIXME Implement Inline Broker's publish mechanism
        initiator_obj = current_domain.from_message(message)
        if message["type"] == "EVENT":
            for subscriber in self._subscribers[
                fully_qualified_name(initiator_obj.__class__)
            ]:
                subscriber_object = subscriber(current_domain, initiator_obj.__class__)
                subscriber_object.notify(initiator_obj.to_dict())
        elif message["type"] == "COMMAND":
            command_handler = current_domain.command_handler_for(
                initiator_obj.__class__
            )
            command_handler()(initiator_obj)
