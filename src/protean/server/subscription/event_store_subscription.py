import asyncio
import logging
import os
import secrets
import socket
import time
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from protean.core.command_handler import BaseCommandHandler
from protean.core.event_handler import BaseEventHandler
from protean.exceptions import ConfigurationError
from protean.port.event_store import BaseEventStore
from protean.utils import fqn
from protean.utils.eventing import Message, MessageType

from . import BaseSubscription

if TYPE_CHECKING:
    from protean.server.engine import Engine

    from .profiles import SubscriptionConfig

logger = logging.getLogger(__name__)


class FailedPositionStatus(StrEnum):
    """Status of a failed position record in the event store."""

    FAILED = "Failed"
    RESOLVED = "Resolved"
    EXHAUSTED = "Exhausted"


class EventStoreSubscription(BaseSubscription):
    """Subscription to an event store stream with failed position recovery.

    Reads messages from a stream category (e.g. ``user``, ``order``) and dispatches
    them to the configured handler. Position tracking, origin-stream filtering, and
    idempotent processing are handled automatically.

    Error Handling
    ~~~~~~~~~~~~~~

    When a handler fails to process a message:

    1. **Read position advances** — the subscription is never blocked by a single
       failing message (avoids the poison-pill problem).
    2. **Failed position is recorded** — a ``Failed`` record is written to a
       dedicated ``failed-{subscriber}-{category}`` stream, capturing the
       global position, per-stream name/position (for later re-read), and
       the current retry count.
    3. **Periodic recovery pass** — ``maybe_run_recovery()`` is called on every
       poll cycle. When ``recovery_interval_seconds`` has elapsed since the last
       pass, it re-reads each unresolved position from the event store and retries
       the handler:

       - **Success** → a ``Resolved`` record is written; the position is removed
         from tracking.
       - **Still failing** → retry count is incremented; a new ``Failed`` record
         is written.
       - **``max_retries`` exceeded** → an ``Exhausted`` record is written; the
         position is permanently removed from tracking and a ``handler.failed``
         trace event is emitted.

    Recovery Checkpoint
    ~~~~~~~~~~~~~~~~~~~

    To avoid re-reading the entire failed-positions stream on every restart,
    ``_rebuild_retry_counts()`` maintains a **checkpoint** in the
    ``recovery-checkpoint-{subscriber}-{category}`` stream. The checkpoint
    stores:

    - **watermark** — the per-stream position in the failed-positions stream
      up to which all records have been processed.
    - **unresolved** — a snapshot of positions still awaiting recovery, so
      they can be restored without re-reading earlier records.

    On restart, only records written *after* the watermark are read and merged
    into the restored snapshot.

    Configuration
    ~~~~~~~~~~~~~

    All recovery parameters can be set in ``domain.toml`` under
    ``[server.event_store_subscription]``:

    - ``max_retries`` (default 3) — retry attempts before marking exhausted.
    - ``retry_delay_seconds`` (default 1) — delay between recovery retries.
    - ``enable_recovery`` (default True) — set to False to disable tracking
      and recovery entirely.
    - ``recovery_interval_seconds`` (default 30) — minimum time between
      recovery passes.
    - ``gap_timeout_seconds`` (default 5) — for a ``$all`` (cross-category)
      subscription, how long to hold at a missing lower ``global_position``
      before abandoning it as a rolled-back gap (see ``_gap_safe_batch``).

    Per-handler overrides can be passed via the constructor or
    ``from_config()`` factory.
    """

    def __init__(
        self,
        engine: "Engine",
        stream_category: str,
        handler: type[BaseEventHandler | BaseCommandHandler],
        messages_per_tick: int = 10,
        position_update_interval: int = 10,
        origin_stream: str | None = None,
        tick_interval: int = 1,
        max_retries: int | None = None,
        retry_delay_seconds: float | None = None,
        enable_recovery: bool | None = None,
        recovery_interval_seconds: float | None = None,
        gap_timeout_seconds: float | None = None,
    ) -> None:
        """
        Initialize the EventStoreSubscription object.

        Args:
            engine: The Protean engine instance.
            stream_category: The name of the stream to subscribe to.
            handler: The event or command handler.
            messages_per_tick: The number of messages to process per tick.
            position_update_interval: The interval at which to update the current position.
            origin_stream: The name of the origin stream to filter messages.
            tick_interval: The interval between ticks.
            max_retries: Maximum retry attempts before marking as exhausted.
            retry_delay_seconds: Delay between recovery retries.
            enable_recovery: Whether to enable failed position recovery.
            recovery_interval_seconds: How often to run the recovery pass.
            gap_timeout_seconds: For a ``$all`` (cross-category) subscription, how
                long to wait for a missing lower ``global_position`` to commit
                before abandoning it as a rolled-back gap.
        """
        # Initialize parent class
        super().__init__(engine, messages_per_tick, tick_interval)

        self.handler = handler
        self.subscriber_name = fqn(self.handler)
        self.subscriber_class_name = self.handler.__name__

        # Generate unique subscription ID
        hostname = socket.gethostname()
        pid = os.getpid()
        random_hex = secrets.token_hex(3)  # 3 bytes = 6 hex digits
        self.subscription_id = (
            f"{self.subscriber_class_name}-{hostname}-{pid}-{random_hex}"
        )

        # Event store specific attributes. The store is Optional on the domain
        # wrapper (None until initialized), but a subscription is only ever
        # constructed after the engine has initialized its event store, so
        # narrow to the non-None type here and fail loudly otherwise.
        store = engine.domain.event_store.store
        if (
            store is None
        ):  # pragma: no cover — defensive; store is initialized by engine startup
            raise ConfigurationError(
                "Event store is not initialized. Cannot create an "
                "EventStoreSubscription before the domain's event store is set up."
            )
        self.store: BaseEventStore = store
        self.stream_category = stream_category
        self.position_update_interval = position_update_interval
        self.origin_stream = origin_stream

        self.subscriber_stream_name = (
            f"position-{self.subscriber_name}-{stream_category}"
        )
        self.current_position: int = -1
        self.messages_since_last_position_write: int = 0

        # Resolve recovery configuration from domain config
        server_config = engine.domain.config.get("server", {})
        es_config = server_config.get("event_store_subscription", {})

        self.max_retries: int = (
            max_retries
            if max_retries is not None
            else int(es_config.get("max_retries", 3))
        )
        self.retry_delay_seconds: float = (
            retry_delay_seconds
            if retry_delay_seconds is not None
            else float(es_config.get("retry_delay_seconds", 1))
        )
        self.enable_recovery: bool = (
            enable_recovery
            if enable_recovery is not None
            else bool(es_config.get("enable_recovery", True))
        )
        self.recovery_interval_seconds: float = (
            recovery_interval_seconds
            if recovery_interval_seconds is not None
            else float(es_config.get("recovery_interval_seconds", 30))
        )
        self.gap_timeout_seconds: float = (
            gap_timeout_seconds
            if gap_timeout_seconds is not None
            else float(es_config.get("gap_timeout_seconds", 5))
        )

        # $all (cross-category) gap tracking: the monotonic time each missing
        # global_position at the contiguity frontier was first observed, used to
        # abandon a gap once it exceeds ``gap_timeout_seconds`` (see
        # ``_gap_safe_batch``). Empty for single-category subscriptions.
        self._gap_first_seen: dict[int, float] = {}
        # The gap-safe watermark computed by the last ``_gap_safe_batch``; ``tick``
        # advances the cursor to it after processing. Stays -1 (a no-op) for
        # single-category subscriptions, which never run the gap logic.
        self._gap_watermark: int = -1

        # Failed position tracking
        self.failed_positions_stream = (
            f"failed-{self.subscriber_name}-{stream_category}"
        )
        self.recovery_checkpoint_stream = (
            f"recovery-checkpoint-{self.subscriber_name}-{stream_category}"
        )
        # In-memory cache of failed position info (populated from event store on init)
        # Maps global_position -> {"retry_count": int, "stream_name": str|None, "stream_position": int|None}
        self._failed_positions: dict[int, dict[str, Any]] = {}
        self._last_recovery_time: float = 0.0

    @classmethod
    def from_config(
        cls,
        engine: "Engine",
        stream_category: str,
        handler: type[BaseEventHandler | BaseCommandHandler],
        config: "SubscriptionConfig",
    ) -> "EventStoreSubscription":
        """Create an EventStoreSubscription instance from a SubscriptionConfig.

        This factory method creates an EventStoreSubscription using configuration
        values from a SubscriptionConfig object. It validates that the config
        is appropriate for an event store subscription.

        Args:
            engine: The Protean engine instance.
            stream_category: The name of the stream to subscribe to.
            handler: The event or command handler.
            config: The subscription configuration object.

        Returns:
            A configured EventStoreSubscription instance.

        Raises:
            ConfigurationError: If config.subscription_type is not EVENT_STORE.

        Example:
            >>> config = SubscriptionConfig.from_profile(SubscriptionProfile.PROJECTION)
            >>> subscription = EventStoreSubscription.from_config(
            ...     engine, "$all", ProjectionHandler, config
            ... )
        """
        # Import here to avoid circular imports
        from .profiles import SubscriptionType  # noqa: PLC0415

        # Validate subscription type
        if config.subscription_type != SubscriptionType.EVENT_STORE:
            raise ConfigurationError(
                f"Cannot create EventStoreSubscription from config with "
                f"subscription_type={config.subscription_type.value}. "
                f"Expected subscription_type=event_store."
            )

        return cls(
            engine=engine,
            stream_category=stream_category,
            handler=handler,
            messages_per_tick=config.messages_per_tick,
            position_update_interval=config.position_update_interval,
            origin_stream=config.origin_stream,
            tick_interval=config.tick_interval,
        )

    async def initialize(self) -> None:
        """
        Perform event store specific initialization.

        This method loads the last position from the event store and rebuilds
        the in-memory retry count cache from the failed positions stream.

        Returns:
            None
        """
        await self.load_position_on_start()

        if self.enable_recovery:
            await self._rebuild_retry_counts()

    async def load_position_on_start(self) -> None:
        """
        Load the last position from the store when starting.

        This method retrieves the last read position from the event store and updates the current position
        of the subscription. If there is no previous position, it logs a message indicating that the
        subscription will start at the beginning of the stream.

        Returns:
            None
        """
        last_position = await self.fetch_last_position()
        if last_position > -1:
            self.current_position = last_position
            logger.debug(f"Loaded position {self.current_position} from last message")
        else:
            logger.debug(
                "No previous messages - Starting at the beginning of the stream"
            )

    async def fetch_last_position(self) -> int:
        """
        Fetch the last read position from the store.

        Returns:
            int: The last read position from the store.
        """
        message = await asyncio.to_thread(
            self.store._read_last_message, self.subscriber_stream_name
        )
        if message:
            position: int = message["data"]["position"]
            return position

        return -1

    async def update_current_position_to_store(self) -> int:
        """Update the current position to the store, only if out of sync.

        This method updates the current position of the subscription to the event store, but only if the
        current position is greater than the last written position.

        Returns:
            int: The last written position.
        """
        last_written_position = await self.fetch_last_position()
        if last_written_position < self.current_position:
            await self.write_position(self.current_position)

        return last_written_position

    async def update_read_position(self, position: int) -> int:
        """
        Update the current read position.

        If at or beyond the configured interval, write position to the store.

        Args:
            position (int): The new read position.

        Returns:
            int: The updated read position.
        """
        self.current_position = position
        self.messages_since_last_position_write += 1

        if self.messages_since_last_position_write >= self.position_update_interval:
            await self.write_position(position)

        return self.current_position

    async def write_position(self, position: int) -> int:
        """
        Write the position to the store.

        This method writes the current read position to the event store. It updates the read position
        of the subscriber and resets the counter for messages since the last position write.

        Args:
            position (int): The read position to be written.

        Returns:
            int: The position that was written.
        """
        logger.debug(f"Updating Read Position of {self.subscriber_name} to {position}")

        self.messages_since_last_position_write = 0  # Reset counter

        return await asyncio.to_thread(
            self.store._write,
            self.subscriber_stream_name,
            "Read",
            {"position": position},
            metadata={
                "headers": {
                    "id": str(uuid4()),
                    "type": "Read",
                    "time": self.engine.domain.clock.now().isoformat(),
                    "stream": self.subscriber_stream_name,
                },
                "domain": {
                    "kind": MessageType.READ_POSITION.value,
                    "origin_stream": self.stream_category,
                },
            },
        )

    def filter_on_origin(self, messages: list[Message]) -> list[Message]:
        """
        Filter messages based on the origin stream name.

        Args:
            messages (List[Message]): The list of messages to filter.

        Returns:
            List[Message]: The filtered list of messages.
        """
        if not self.origin_stream:
            return messages

        filtered_messages = []

        for message in messages:
            origin_stream = (
                message.metadata
                and message.metadata.domain
                and self.store.category(message.metadata.domain.origin_stream or "")
            )

            if self.origin_stream == origin_stream:
                filtered_messages.append(message)

        logger.debug(f"Filtered {len(filtered_messages)} out of {len(messages)}")
        return filtered_messages

    async def tick(self) -> None:
        """Process one batch, then step the cursor over any abandoned ``$all`` gaps.

        Extends the base tick: after ``process_batch`` has carried the present
        messages forward (one at a time, so an interrupted batch leaves the cursor
        at the last one actually processed), advance ``current_position`` to the
        gap-safe watermark set by ``_gap_safe_batch``. This steps over abandoned
        holes, which carry no message for ``process_batch`` to advance through.
        Running it *after* ``process_batch`` is what keeps it crash-safe — an
        exception there skips this and leaves the cursor at real progress. It is a
        no-op for single-category subscriptions (``_gap_watermark`` stays -1).
        """
        messages = await self.get_next_batch_of_messages()
        if messages:
            await self.process_batch(messages)

        if self._gap_watermark > self.current_position:
            await self.update_read_position(self._gap_watermark)

    async def get_next_batch_of_messages(self) -> list[Message]:
        """
        Get the next batch of messages to process.

        This method reads messages from the event store starting from the current position + 1.
        It retrieves a specified number of messages per tick and applies filtering based on the origin stream name.

        Returns:
            List[Message]: The next batch of messages to process.
        """
        messages = await asyncio.to_thread(
            self.store.read,
            self.stream_category,
            position=self.current_position + 1,
            no_of_messages=self.messages_per_tick,
        )

        if self.stream_category == "$all":
            messages = self._gap_safe_batch(messages)

        return self.filter_on_origin(messages)

    def _gap_safe_batch(self, messages: list[Message]) -> list[Message]:
        """Hold a ``$all`` (cross-category) batch at the first ``global_position`` gap.

        ``global_position`` is a store-wide sequence. Within a single category the
        store assigns it in commit order, so a single-category subscription never
        sees a gap. Across categories it can be assigned out of commit order — a
        lower position committing *after* a higher one — so advancing past the
        highest position seen would silently skip the late-committing lower one
        (the checkpoint gap this guards against).

        The core of the fix is a low-watermark: process only the contiguous run
        from ``current_position + 1``, stopping at the first missing
        position and waiting for it to commit. A rolled-back append permanently
        consumes a ``global_position``, so a gap that persists longer than
        ``gap_timeout_seconds`` is abandoned (skipped) rather than waited on
        forever. Positions above an unfilled gap are held until it resolves.

        Records the settled watermark in ``self._gap_watermark`` (``tick`` advances
        the cursor to it *after* processing, so an interrupted batch is not skipped)
        and returns the prefix of ``messages`` safe to process now (those at or
        below it); an empty list means "hold this tick".
        """
        positioned = [
            (m.metadata.event_store.global_position, m)
            for m in messages
            if m.metadata
            and m.metadata.event_store
            and m.metadata.event_store.global_position is not None
        ]
        if len(positioned) < len(
            messages
        ):  # pragma: no cover — real store messages always carry a position
            # The gap walk needs a global_position, so records without one are
            # dropped here rather than in ``process_batch``. Log it so the drop
            # (a sign of a malformed store record) is not silent.
            logger.warning(
                f"[{self.subscriber_class_name}] Skipping "
                f"{len(messages) - len(positioned)} $all record(s) with no "
                f"global_position"
            )
        if not positioned:
            # Empty batch, or (defensively) only records missing a position: no
            # frontier to gate, so clear the gap timers and let the downstream
            # corruption guard handle any position-less records.
            self._gap_first_seen.clear()
            self._gap_watermark = self.current_position
            return messages

        now = time.monotonic()
        present = {position for position, _ in positioned}
        highest = max(present)
        # ``global_position`` is 1-based, so a fresh subscription (current == -1)
        # expects position 1, not 0 — clamp to the sequence floor so the first
        # real position is not mistaken for a gap.
        expected = max(self.current_position + 1, 1)
        safe = self.current_position
        while expected <= highest:
            if expected in present:
                self._gap_first_seen.pop(expected, None)
                safe = expected
            else:
                first_seen = self._gap_first_seen.setdefault(expected, now)
                if now - first_seen < self.gap_timeout_seconds:
                    break  # hold — wait for the gap to fill
                logger.warning(
                    f"[{self.subscriber_class_name}] Abandoning gap at "
                    f"global_position {expected} after {self.gap_timeout_seconds}s "
                    f"(assumed rolled back)"
                )
                self._gap_first_seen.pop(expected, None)
                safe = expected
            expected += 1

        # Record the settled watermark. ``tick`` advances ``current_position`` to
        # it *after* ``process_batch`` completes, which is what keeps this
        # crash-safe: present messages are carried forward one at a time by
        # ``process_batch`` (an interrupted batch leaves the cursor at the last
        # one actually processed), while abandoned holes — which carry no message,
        # so ``process_batch`` cannot move past them — are stepped over only once
        # the batch is done. Timers for settled positions were popped in the loop;
        # only frontier/ahead gaps remain, and they age monotonically
        # (``setdefault`` never resets).
        self._gap_watermark = safe

        return [message for position, message in positioned if position <= safe]

    async def process_batch(self, messages: list[Message]) -> int:
        """
        Process a batch of messages.

        This method takes a batch of messages and processes each message by calling the `handle_message` method
        of the engine. It also updates the read position after processing each message.

        When a handler fails:
        - The read position is still advanced (non-blocking — avoids poison pill)
        - The failed position is recorded to a dedicated stream for later recovery
        - The ``handle_error()`` callback is invoked by the engine

        Messages with an idempotency key that have already been processed (recorded
        as ``status: success`` in the idempotency store) are skipped to prevent
        duplicate handling after crash recovery or subscription replay.

        Args:
            messages (List[Message]): The batch of messages to process.

        Returns:
            int: The number of messages processed successfully.
        """
        successful_count = 0

        # Get the idempotency store (may be inactive if Redis is not configured)
        idempotency_store = self.engine.domain.idempotency_store

        for message in messages:
            # Messages read from the event store are always deserialized with
            # metadata (headers + store positions). Guard defensively so a
            # malformed record is skipped rather than crashing the batch.
            if (
                message.metadata is None
                or message.metadata.event_store is None
                or message.metadata.event_store.global_position is None
            ):  # pragma: no cover — corruption guard; real store messages always carry these
                logger.warning(
                    f"[{self.subscriber_class_name}] "
                    f"Skipping message with missing metadata/position"
                )
                continue

            message_type = message.metadata.headers.type or "unknown"
            message_id = message.metadata.headers.id or "unknown"
            short_id = message_id[:8]
            position = message.metadata.event_store.global_position

            # Log the message being picked up, with payload
            logger.info(
                f"[{self.subscriber_class_name}] "
                f"Received {message_type} (ID: {short_id}..., pos: {position})\n"
                f"  Payload: {message.to_dict()}"
            )

            # Skip synchronous messages — they were already handled inline
            if not (message.metadata.domain and message.metadata.domain.asynchronous):
                logger.info(
                    f"[{self.subscriber_class_name}] "
                    f"{message_type} (pos: {position}) — already processed inline"
                )
                await self.update_read_position(position)
                continue

            # Check idempotency store for already-processed commands
            idempotency_key = (
                message.metadata.headers.idempotency_key
                if message.metadata.headers
                else None
            )
            if idempotency_key and idempotency_store.is_active:
                existing = idempotency_store.check(idempotency_key)
                if existing and existing.get("status") == "success":
                    logger.info(
                        f"[{self.subscriber_class_name}] "
                        f"{message_type} (ID: {short_id}...) — already processed (idempotent)"
                    )
                    await self.update_read_position(position)
                    successful_count += 1
                    continue

            # Process the message and get a success/failure result
            is_successful = await self.engine.handle_message(
                self.handler, message, worker_id=self.subscription_id
            )

            # Always update position to avoid reprocessing the message
            await self.update_read_position(position)

            # Record success in idempotency store for future dedup
            if is_successful and idempotency_key and idempotency_store.is_active:
                idempotency_store.record_success(idempotency_key, True)

            if is_successful:
                successful_count += 1
                logger.info(
                    f"[{self.subscriber_class_name}] "
                    f"Completed {message_type} (ID: {short_id}..., pos: {position})"
                )
            else:
                logger.warning(
                    f"[{self.subscriber_class_name}] "
                    f"Failed {message_type} (ID: {short_id}..., pos: {position})"
                )
                # Record the failed position for later recovery
                if self.enable_recovery:
                    stream_name = (
                        message.metadata.headers.stream
                        if message.metadata.headers
                        else None
                    )
                    stream_position = (
                        message.metadata.event_store.position
                        if message.metadata.event_store
                        else None
                    )
                    await self._record_failed_position(
                        position,
                        message_type,
                        message_id,
                        stream_name=stream_name,
                        stream_position=stream_position,
                    )

        return successful_count

    # ──────────────────────────────────────────────────────────────────────
    # Failed Position Tracking
    # ──────────────────────────────────────────────────────────────────────

    async def _record_failed_position(
        self,
        position: int,
        message_type: str,
        message_id: str,
        stream_name: str | None = None,
        stream_position: int | None = None,
    ) -> None:
        """Record a failed position to the failed-positions stream.

        Writes a ``Failed`` record containing the position, message metadata,
        and current retry count. This allows the recovery pass to find and
        retry the message later.

        Args:
            position: The global position of the failed message.
            message_type: The type string of the failed message.
            message_id: The ID of the failed message.
            stream_name: The specific stream name (e.g., ``user-123``).
            stream_position: The per-stream position of the message.
        """
        existing = self._failed_positions.get(position, {})
        retry_count = existing.get("retry_count", 0)

        self._failed_positions[position] = {
            "retry_count": retry_count,
            "stream_name": stream_name,
            "stream_position": stream_position,
        }

        logger.info(
            f"[{self.subscriber_class_name}] Recording failed position {position} "
            f"(retry {retry_count}/{self.max_retries})"
        )

        await asyncio.to_thread(
            self.store._write,
            self.failed_positions_stream,
            FailedPositionStatus.FAILED.value,
            {
                "position": position,
                "message_type": message_type,
                "message_id": message_id,
                "retry_count": retry_count,
                "stream_name": stream_name,
                "stream_position": stream_position,
            },
            metadata={
                "headers": {
                    "id": str(uuid4()),
                    "type": FailedPositionStatus.FAILED.value,
                    "time": self.engine.domain.clock.now().isoformat(),
                    "stream": self.failed_positions_stream,
                },
                "domain": {
                    "kind": MessageType.READ_POSITION.value,
                    "origin_stream": self.stream_category,
                },
            },
        )

    async def _write_recovery_status(
        self,
        position: int,
        status: FailedPositionStatus,
        retry_count: int,
        message_type: str = "unknown",
        message_id: str = "unknown",
    ) -> None:
        """Write a recovery status record (Resolved or Exhausted) to the failed-positions stream.

        Args:
            position: The global position of the message.
            status: The recovery status to record.
            retry_count: The current retry count.
            message_type: The type string of the message.
            message_id: The ID of the message.
        """
        await asyncio.to_thread(
            self.store._write,
            self.failed_positions_stream,
            status.value,
            {
                "position": position,
                "message_type": message_type,
                "message_id": message_id,
                "retry_count": retry_count,
            },
            metadata={
                "headers": {
                    "id": str(uuid4()),
                    "type": status.value,
                    "time": self.engine.domain.clock.now().isoformat(),
                    "stream": self.failed_positions_stream,
                },
                "domain": {
                    "kind": MessageType.READ_POSITION.value,
                    "origin_stream": self.stream_category,
                },
            },
        )

    # ──────────────────────────────────────────────────────────────────────
    # Recovery Pass
    # ──────────────────────────────────────────────────────────────────────

    async def _rebuild_retry_counts(self) -> None:
        """Rebuild the in-memory failed positions cache from the failed-positions stream.

        Uses a checkpoint to avoid re-reading the entire failed-positions stream
        on every restart. The checkpoint stores the per-stream position of the
        last record processed and a snapshot of unresolved positions at that
        point. On rebuild, only records written after the checkpoint are read
        and merged into the restored snapshot.

        When no checkpoint exists (first run), the entire stream is read from
        position 0. After processing, a new checkpoint is written so that
        subsequent rebuilds start from where this one left off.
        """
        # Restore from checkpoint if available
        watermark = 0
        checkpoint = await asyncio.to_thread(
            self.store._read_last_message, self.recovery_checkpoint_stream
        )
        if checkpoint:
            watermark = checkpoint["data"].get("watermark", 0)
            # Restore the unresolved positions snapshot from the checkpoint
            snapshot = checkpoint["data"].get("unresolved", {})
            self._failed_positions = {int(pos): info for pos, info in snapshot.items()}
            logger.debug(
                f"[{self.subscriber_class_name}] Restored checkpoint at watermark "
                f"{watermark} with {len(self._failed_positions)} unresolved position(s)"
            )

        # Read only new records since the checkpoint
        messages = await asyncio.to_thread(
            self.store.read,
            self.failed_positions_stream,
            position=watermark,
            no_of_messages=10000,
        )

        if messages:
            # Process new records to update state
            for msg in messages:
                pos = msg.data.get("position")
                status = (
                    msg.metadata.headers.type
                    if msg.metadata and msg.metadata.headers
                    else None
                )
                if pos is None or status is None:
                    continue

                if status in (
                    FailedPositionStatus.RESOLVED.value,
                    FailedPositionStatus.EXHAUSTED.value,
                ):
                    # Terminal — remove from tracking
                    self._failed_positions.pop(pos, None)
                elif status == FailedPositionStatus.FAILED.value:
                    # New or updated failure
                    self._failed_positions[pos] = {
                        "retry_count": msg.data.get("retry_count", 0),
                        "stream_name": msg.data.get("stream_name"),
                        "stream_position": msg.data.get("stream_position"),
                    }

            # Compute new watermark: per-stream position after the last record + 1
            last_msg = messages[-1]
            new_watermark = (
                last_msg.metadata.event_store.position + 1
                if last_msg.metadata
                and last_msg.metadata.event_store
                and last_msg.metadata.event_store.position is not None
                else watermark
            )

            # Write checkpoint
            await self._write_recovery_checkpoint(new_watermark)

        if self._failed_positions:
            logger.info(
                f"[{self.subscriber_class_name}] Rebuilt retry counts: "
                f"{len(self._failed_positions)} failed position(s) pending recovery"
            )

    async def _write_recovery_checkpoint(self, watermark: int) -> None:
        """Write a recovery checkpoint with the current watermark and unresolved positions.

        The checkpoint is an append-only record in the checkpoint stream. Only the
        last record is read on startup (via ``_read_last_message``), so earlier
        checkpoint records are harmless but never cleaned up. Since the event store
        is append-only with no truncation, the checkpoint stream grows by one
        record per restart — negligible in practice.

        Args:
            watermark: The per-stream position to start reading from on next rebuild.
        """
        # Serialize _failed_positions with string keys for JSON compatibility
        snapshot = {str(pos): info for pos, info in self._failed_positions.items()}

        await asyncio.to_thread(
            self.store._write,
            self.recovery_checkpoint_stream,
            "Checkpoint",
            {
                "watermark": watermark,
                "unresolved": snapshot,
            },
            metadata={
                "headers": {
                    "id": str(uuid4()),
                    "type": "Checkpoint",
                    "time": self.engine.domain.clock.now().isoformat(),
                    "stream": self.recovery_checkpoint_stream,
                },
                "domain": {
                    "kind": MessageType.READ_POSITION.value,
                    "origin_stream": self.stream_category,
                },
            },
        )

    def _get_unresolved_positions(self) -> dict[int, dict[str, Any]]:
        """Get positions that need recovery (still in Failed state).

        Returns:
            Dict mapping global_position -> info dict for unresolved positions.
        """
        return dict(self._failed_positions)

    async def run_recovery_pass(self) -> int:
        """Run a recovery pass over all failed positions.

        For each unresolved failed position:
        1. Re-read the original message from the event store using its stream name
        2. Retry the handler
        3. On success: write a ``Resolved`` record
        4. On max_retries exhausted: write an ``Exhausted`` record

        Returns:
            int: The number of positions recovered successfully.
        """
        unresolved = self._get_unresolved_positions()
        if not unresolved:
            return 0

        logger.info(
            f"[{self.subscriber_class_name}] Recovery pass: "
            f"{len(unresolved)} position(s) to retry"
        )

        recovered_count = 0

        for position, info in unresolved.items():
            retry_count = info.get("retry_count", 0)
            stream_name = info.get("stream_name")
            stream_position = info.get("stream_position")

            # Increment retry count
            new_retry_count = retry_count + 1

            if new_retry_count > self.max_retries:
                # Exhausted — mark as permanently failed
                logger.warning(
                    f"[{self.subscriber_class_name}] Position {position} exhausted "
                    f"after {self.max_retries} retries"
                )
                await self._write_recovery_status(
                    position, FailedPositionStatus.EXHAUSTED, new_retry_count
                )
                # Remove from in-memory tracking
                self._failed_positions.pop(position, None)

                # Emit handler.failed trace for exhausted position
                self.engine.emitter.emit(
                    event="handler.failed",
                    stream=self.stream_category,
                    message_id=f"pos-{position}",
                    message_type="recovery",
                    status="exhausted",
                    handler=self.subscriber_class_name,
                    error=f"Exhausted after {self.max_retries} retries",
                    worker_id=self.subscription_id,
                )
                continue

            # Re-read the original message from the event store.
            # Use the specific stream name and per-stream position if available,
            # otherwise fall back to reading from the category stream.
            if stream_name and stream_position is not None:
                messages = await asyncio.to_thread(
                    self.store.read,
                    stream_name,
                    position=stream_position,
                    no_of_messages=1,
                )
            else:
                messages = await asyncio.to_thread(
                    self.store.read,
                    self.stream_category,
                    position=position,
                    no_of_messages=1,
                )

            if not messages:
                logger.warning(
                    f"[{self.subscriber_class_name}] Could not find message at "
                    f"position {position} for recovery"
                )
                continue

            message = messages[0]

            # Resolve message type/id defensively — a re-read message always
            # carries metadata, but the type allows None, so fall back to
            # "unknown" (matching the ``or "unknown"`` intent below).
            headers = message.metadata.headers if message.metadata else None
            recovered_message_type = (headers.type if headers else None) or "unknown"
            recovered_message_id = (headers.id if headers else None) or "unknown"

            # Apply retry delay
            if self.retry_delay_seconds > 0:
                await asyncio.sleep(self.retry_delay_seconds)

            # Retry the handler
            logger.info(
                f"[{self.subscriber_class_name}] Retrying position {position} "
                f"(attempt {new_retry_count}/{self.max_retries})"
            )

            is_successful = await self.engine.handle_message(
                self.handler, message, worker_id=self.subscription_id
            )

            if is_successful:
                logger.info(
                    f"[{self.subscriber_class_name}] Recovered position {position}"
                )
                await self._write_recovery_status(
                    position,
                    FailedPositionStatus.RESOLVED,
                    new_retry_count,
                    message_type=recovered_message_type,
                    message_id=recovered_message_id,
                )
                self._failed_positions.pop(position, None)
                recovered_count += 1
            else:
                # Still failing — update in-memory state and write new Failed record
                logger.warning(
                    f"[{self.subscriber_class_name}] Position {position} still failing "
                    f"(attempt {new_retry_count}/{self.max_retries})"
                )
                self._failed_positions[position] = {
                    "retry_count": new_retry_count,
                    "stream_name": stream_name,
                    "stream_position": stream_position,
                }
                await self._record_failed_position(
                    position,
                    recovered_message_type,
                    recovered_message_id,
                    stream_name=stream_name,
                    stream_position=stream_position,
                )

        return recovered_count

    async def maybe_run_recovery(self) -> int:
        """Run a recovery pass if enough time has elapsed since the last one.

        Returns:
            int: The number of positions recovered, or 0 if recovery was skipped.
        """
        if not self.enable_recovery:
            return 0

        now = time.monotonic()
        if now - self._last_recovery_time < self.recovery_interval_seconds:
            return 0

        self._last_recovery_time = now
        return await self.run_recovery_pass()

    async def poll(self) -> None:
        """
        Polling loop for processing messages.

        Extends the base poll loop to periodically run recovery passes
        for failed positions.
        """
        consecutive_errors = 0

        while self.keep_going and not self.engine.shutting_down:
            try:
                with self.engine.domain.domain_context():
                    # Process new messages
                    await self.tick()

                    # Periodically attempt recovery of failed positions
                    await self.maybe_run_recovery()

                    # Reset error counter on successful tick
                    consecutive_errors = 0

                    # Use minimal sleep for cooperative multitasking
                    if self.tick_interval > 0:
                        await asyncio.sleep(self.tick_interval)
                    else:
                        await asyncio.sleep(0)

            except asyncio.CancelledError:
                logger.info(f"Subscription cancelled: {self.subscriber_name}")
                break

            except Exception as exc:
                consecutive_errors += 1
                logger.exception(
                    f"Error in subscription {self.subscriber_name} "
                    f"(attempt {consecutive_errors}): {exc}"
                )
                # Exponential backoff: 1s, 2s, 4s, 8s, ... capped at 30s
                backoff = min(2 ** (consecutive_errors - 1), 30)
                await asyncio.sleep(backoff)

    async def cleanup(self) -> None:
        """
        Perform cleanup tasks during shutdown.

        This method updates the current position to the store during shutdown.

        Returns:
            None
        """
        await self.update_current_position_to_store()
