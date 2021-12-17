import asyncio
import json

from typing import Union

from protean import BaseCommandHandler, BaseEventHandler
from protean.port import BaseEventStore


class Subscription:
    """Subscriber implementation."""

    def __init__(
        self,
        event_store: BaseEventStore,
        loop: asyncio.BaseEventLoop,
        subscriber_id: str,
        stream_name: str,
        handler: Union[BaseEventHandler, BaseCommandHandler],
        messages_per_tick: int = 10,
        position_update_interval: int = 10,
        origin_stream_name: str = None,
        tick_interval: int = 1,
        test_mode: bool = False,
    ) -> None:
        self.event_store = event_store
        self.loop = loop

        self.subscriber_id = subscriber_id
        self.stream_name = stream_name
        self.handler = handler
        self.messages_per_tick = messages_per_tick
        self.position_update_interval = position_update_interval
        self.origin_stream_name = origin_stream_name
        self.tick_interval = tick_interval

        self.subscriber_stream_name = f"subscriber_position-${subscriber_id}"

        self.current_position: int = 0
        self.messages_since_last_position_write: int = 0

        self.keep_going: bool = not test_mode

    async def load_position(self):
        print(f"Loading position... {self.subscriber_id}")
        message = self.event_store._read_last_message(self.subscriber_stream_name)
        if message:
            data = json.loads(message["data"])
            self.current_position = data["position"]
        else:
            self.current_position = 0

    async def update_read_position(self, position):
        self.current_position = position
        self.messages_since_last_position_write += 1

        if self.messages_since_last_position_write == self.position_update_interval:
            return self.write_position(position)

        return

    def write_position(self, position):
        print(f"Updating Read Position... {self.subscriber_id} - {position}")

        self.messages_since_last_position_write = 0
        return self.event_store._write(
            self.subscriber_stream_name, "Read", {"position": position}
        )

    async def get_next_batch_of_messages(self):
        return self.event_store._read(
            self.stream_name,
            position=self.current_position + 1,
            no_of_messages=self.messages_per_tick,
        )  # FIXME Implement filtering

    async def process_batch(self, messages):
        print(f"Processing {len(messages)}...")
        for message in messages:
            try:
                await self.handle_message(message)
                print(
                    f"Position: {message['position']}, Global Position: {message['global_position']}"
                )
                await self.update_read_position(message["global_position"])
            except Exception as exc:
                self.log_error(message, exc)

        return len(messages)

    def log_error(self, last_message, error):
        print(f"{str(error) - {last_message}}")

    async def handle_message(self, message):
        for handler in self.handler()._handlers[message["type"]]:
            handler_method = getattr(self.handler(), handler.__name__)
            return handler_method(message["data"])

    async def start(self):
        print(f"Starting {self.subscriber_id}...")

        # Load own position from Event store
        await self.load_position()
        self.loop.create_task(self.poll())

    async def poll(self):
        print(f"Polling for {self.subscriber_id}")
        await self.tick()

        if self.keep_going:
            await asyncio.sleep(self.tick_interval)
            self.loop.create_task(self.poll())

    async def tick(self):
        messages = await self.get_next_batch_of_messages()
        if messages:
            return await self.process_batch(messages)
