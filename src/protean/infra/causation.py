"""Causation tracing over an event-store adapter.

Every message carries its own ID (``headers.id``), the ID of the message that
caused it (``causation_id``) and the ID shared by every message of one request
(``correlation_id``). These functions read a store through its
`EventStorePort` members and follow those IDs: up to the root
(`trace_causation`), down to the effects (`trace_effects`), or across a whole
correlation group (`build_causation_tree`).

They scan ``$all`` and filter in memory, so they suit debugging and
inspection.
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import TYPE_CHECKING, Any

from protean.utils.eventing import Message

if TYPE_CHECKING:
    from protean.port.event_store import EventStorePort, RawMessage


@dataclass
class CausationNode:
    """A node in the causation tree, representing a single message and its effects."""

    message_id: str
    message_type: str
    kind: str  # "EVENT" or "COMMAND"
    stream: str
    time: str | None
    global_position: int | None
    children: list[CausationNode] = dc_field(default_factory=list)
    handler: str | None = None
    duration_ms: float | None = None
    delta_ms: float | None = None


def _extract_message_id(msg: Mapping[str, Any]) -> str | None:
    """Extract the Protean message ID (headers.id) from a raw message dict."""
    metadata = msg.get("metadata")
    if not metadata or not isinstance(metadata, dict):
        return None
    headers = metadata.get("headers")
    if not headers or not isinstance(headers, dict):
        return None
    message_id: str | None = headers.get("id")
    return message_id


def _extract_causation_id(msg: Mapping[str, Any]) -> str | None:
    """Extract causation_id from a raw message dict."""
    metadata = msg.get("metadata")
    if not metadata or not isinstance(metadata, dict):
        return None
    domain = metadata.get("domain")
    if not domain or not isinstance(domain, dict):
        return None
    causation_id: str | None = domain.get("causation_id")
    return causation_id


def _extract_correlation_id(msg: Mapping[str, Any]) -> str | None:
    """Extract correlation_id from a raw message dict."""
    metadata = msg.get("metadata")
    if not metadata or not isinstance(metadata, dict):
        return None
    domain = metadata.get("domain")
    if not domain or not isinstance(domain, dict):
        return None
    correlation_id: str | None = domain.get("correlation_id")
    return correlation_id


def load_correlation_group(
    adapter: EventStorePort, correlation_id: str
) -> list[RawMessage]:
    """Return every raw message in ``adapter`` whose ``correlation_id`` matches.

    Reads the first 1,000,000 rows of ``$all`` with
    ``adapter.get_all_messages`` and keeps the adapter's order, which is
    ``global_position`` order on the memory and Message DB stores. The list
    is new on each call, so a caller may sort or change it.
    """
    all_messages = adapter.get_all_messages(limit=1_000_000)
    return [m for m in all_messages if _extract_correlation_id(m) == correlation_id]


def _ids_from_message(message: Message) -> tuple[str | None, str | None]:
    """Return the message's ``headers.id`` and ``correlation_id``."""
    mid = (
        message.metadata.headers.id
        if message.metadata and message.metadata.headers
        else None
    )
    cid = (
        message.metadata.domain.correlation_id
        if message.metadata and message.metadata.domain
        else None
    )
    return mid, cid


def _scan_for_group(adapter: EventStorePort, message_id: str) -> list[RawMessage]:
    """Return the correlation group of the message with ID ``message_id``.

    Raises:
        ValueError: No message in the store has that ID.
    """
    # String ID: single pass to find the target and its group
    all_messages = adapter.get_all_messages(limit=1_000_000)
    target_correlation_id: str | None = None
    for m in all_messages:
        if _extract_message_id(m) == message_id:
            target_correlation_id = _extract_correlation_id(m)
            break

    if target_correlation_id is None:
        raise ValueError(f"Message with ID '{message_id}' not found in event store")

    return [
        m for m in all_messages if _extract_correlation_id(m) == target_correlation_id
    ]


def _resolve_and_load_group(
    adapter: EventStorePort, message_id: str | Message
) -> tuple[str, list[RawMessage]]:
    """Resolve a message identifier and load its full correlation group.

    When ``message_id`` is a `Message`, the correlation ID is read
    directly from metadata (no scan required).  When it is a ``str``, a
    single pass over ``$all`` finds the message and its correlation group.

    Returns:
        Tuple of ``(resolved_message_id, correlation_group)``.

    Raises:
        ValueError: If the message cannot be found in the event store.
    """
    if isinstance(message_id, Message):
        mid, cid = _ids_from_message(message_id)
        if mid is None:
            raise ValueError("Message has no headers.id")
        if cid is None:
            return mid, []
        group = load_correlation_group(adapter, cid)
        return mid, group

    return message_id, _scan_for_group(adapter, message_id)


def trace_causation(
    adapter: EventStorePort, message_id: str | Message
) -> list[Message]:
    """Return the causation chain from the root message down to ``message_id``.

    Args:
        adapter: The event store to read.
        message_id: A Protean message ID string (``headers.id``) or
            a `Message` object.

    Returns:
        `Message` objects in causal order, root first and the given message
        last.

    Raises:
        ValueError: If the message cannot be found in the event store.
    """
    mid, group = _resolve_and_load_group(adapter, message_id)

    # Build lookup: headers.id -> raw_message
    by_id: dict[str, RawMessage] = {}
    for m in group:
        hid = _extract_message_id(m)
        if hid:
            by_id[hid] = m

    # Walk up from target to root
    chain: list[RawMessage] = []
    current_id: str | None = mid
    visited: set[str] = set()

    while current_id and current_id not in visited:
        visited.add(current_id)
        raw_msg = by_id.get(current_id)
        if raw_msg is None:
            break
        chain.append(raw_msg)
        current_id = _extract_causation_id(raw_msg)

    # Reverse so root is first
    chain.reverse()

    return [Message.deserialize(m) for m in chain]


def trace_effects(
    adapter: EventStorePort, message_id: str | Message, *, recursive: bool = True
) -> list[Message]:
    """Return the messages caused by ``message_id``.

    Args:
        adapter: The event store to read.
        message_id: A Protean message ID string (``headers.id``) or
            a `Message` object.
        recursive: If ``True`` (default), return the full subtree of
            effects.  If ``False``, return only direct children.

    Returns:
        `Message` objects caused by the given message, ordered by
        ``global_position``. The given message itself is not included.

    Raises:
        ValueError: If the message cannot be found in the event store.
    """
    mid, group = _resolve_and_load_group(adapter, message_id)

    # Build children lookup: causation_id -> [raw_messages]
    children: dict[str, list[RawMessage]] = defaultdict(list)
    for m in group:
        cid = _extract_causation_id(m)
        if cid:
            children[cid].append(m)

    if not recursive:
        direct = children.get(mid, [])
        direct.sort(key=lambda m: m.get("global_position", 0))
        return [Message.deserialize(m) for m in direct]

    # BFS for full subtree
    result: list[RawMessage] = []
    queue: deque[str] = deque([mid])
    visited: set[str] = {mid}

    while queue:
        current = queue.popleft()
        for child in children.get(current, []):
            child_id = _extract_message_id(child)
            if child_id and child_id not in visited:
                visited.add(child_id)
                result.append(child)
                queue.append(child_id)

    result.sort(key=lambda m: m.get("global_position", 0))
    return [Message.deserialize(m) for m in result]


def build_causation_tree(
    adapter: EventStorePort, correlation_id: str
) -> CausationNode | None:
    """Build a full causation tree for a correlation ID.

    Returns the root node of the tree with children recursively populated.

    Args:
        adapter: The event store to read.
        correlation_id: The correlation ID to trace.

    Returns:
        Root [`CausationNode`][protean.infra.causation.CausationNode] with
        children, or ``None`` if no messages found.
    """
    return build_tree_from_group(load_correlation_group(adapter, correlation_id))


def build_tree_from_group(
    group: Sequence[Mapping[str, Any]],
) -> CausationNode | None:
    """Build the causation tree of an already-loaded correlation group.

    The root is the earliest message with no ``causation_id``. When every
    message has one, it is the earliest whose ``causation_id`` names a message
    outside the group, or else the first message. Children are ordered by
    ``global_position``. Each node's ``time`` is the row's ``time`` written with
    ``isoformat()`` when the value has that method, and with ``str()``
    otherwise. Its ``handler``, ``duration_ms`` and ``delta_ms`` are ``None``.

    Returns:
        The root node, or ``None`` when ``group`` is empty.
    """
    if not group:
        return None

    by_id, children_map, roots = _index_group(group)
    roots = _pick_roots(group, by_id, roots)
    visited: set[str] = set()
    return _causation_node(roots[0], children_map, visited)


def _index_group(
    group: Sequence[Mapping[str, Any]],
) -> tuple[
    dict[str, Mapping[str, Any]],
    dict[str, list[Mapping[str, Any]]],
    list[Mapping[str, Any]],
]:
    """Index a correlation group for the causation tree.

    Returns the messages by ``headers.id``, the children of each message by
    its ID sorted by ``global_position``, and the messages with no
    causation ID.
    """
    by_id: dict[str, Mapping[str, Any]] = {}
    children_map: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    roots: list[Mapping[str, Any]] = []

    for m in group:
        hid = _extract_message_id(m)
        if hid:
            by_id[hid] = m
        cid = _extract_causation_id(m)
        if cid:
            children_map[cid].append(m)
        else:
            roots.append(m)

    # Sort children by global_position for deterministic ordering
    for children in children_map.values():
        children.sort(key=lambda m: m.get("global_position", 0))

    return by_id, children_map, roots


def _pick_roots(
    group: Sequence[Mapping[str, Any]],
    by_id: dict[str, Mapping[str, Any]],
    roots: list[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    """Return the root candidates of the causation tree, sorted by
    ``global_position``. The list is never empty for a non-empty group."""
    if not roots:
        # All messages have causation_id set: pick the one whose
        # causation_id points outside the group
        root_candidates = [m for m in group if _extract_causation_id(m) not in by_id]
        roots = root_candidates if root_candidates else [group[0]]

    roots.sort(key=lambda m: m.get("global_position", 0))
    return roots


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _time_str(time_val: Any) -> str | None:
    """Return ``time_val.isoformat()`` when it has that method, else ``str(time_val)``.

    Returns ``None`` when ``time_val`` is empty.
    """
    if not time_val:
        return None
    if hasattr(time_val, "isoformat"):
        iso: str = time_val.isoformat()
        return iso
    return str(time_val)


def _causation_node(
    raw_msg: Mapping[str, Any],
    children_map: dict[str, list[Mapping[str, Any]]],
    visited: set[str],
) -> CausationNode:
    """Build the node for ``raw_msg`` and, recursively, its unvisited children.

    Adds each built message's ID to ``visited``.
    """
    hid = _extract_message_id(raw_msg) or "?"
    visited.add(hid)

    metadata = _dict_or_empty(raw_msg.get("metadata", {}))
    headers = _dict_or_empty(metadata.get("headers", {}))
    domain_meta = _dict_or_empty(metadata.get("domain", {}))

    node = CausationNode(
        message_id=hid,
        message_type=raw_msg.get("type", headers.get("type", "?")),
        kind=domain_meta.get("kind", "?"),
        stream=raw_msg.get("stream_name", headers.get("stream", "?")),
        time=_time_str(raw_msg.get("time")),
        global_position=raw_msg.get("global_position"),
    )

    for child_msg in children_map.get(hid, []):
        child_id = _extract_message_id(child_msg)
        if child_id and child_id not in visited:
            node.children.append(_causation_node(child_msg, children_map, visited))

    return node
