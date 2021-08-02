import json

from typing import Dict

from queue import Queue, Empty

from protean.port.broker import BaseBroker

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from protean.domain import Domain


class InlineBroker(BaseBroker):
    def __init__(self, name: str, domain: "Domain", conn_info: Dict[str, str]) -> None:
        super().__init__(name, domain, conn_info)

        # In case of `InlineBroker`, the `IS_ASYNC` value will always be `False`.
        conn_info["IS_ASYNC"] = False

        self._queue = Queue()

    def publish(self, message: Dict) -> None:
        self._queue.put(json.dumps(message))

    def get_next(self) -> Dict:
        try:
            bytes_message = self._queue.get_nowait()
        except Empty:
            return None

        return json.loads(bytes_message)

    def _data_reset(self) -> None:
        with self._queue.mutex:
            self._queue.queue.clear()
