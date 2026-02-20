"""Upcasting infrastructure for event schema evolution.

:class:`UpcasterChain` is built during ``domain.init()`` and provides
efficient lookup and chained transformation of old event payloads to the
current schema version.

Usage is fully internal — the chain is consulted by
:meth:`Message.to_domain_object` when a stored type string has no direct
match in ``_events_and_commands``.
"""

from __future__ import annotations

import logging
from typing import Any

from protean.exceptions import ConfigurationError

logger = logging.getLogger(__name__)


class UpcasterChain:
    """Build, validate, and apply upcaster chains for all event types.

    During domain initialisation upcasters are registered as directed edges
    ``(from_version) → (to_version)`` grouped by *event_base_type* (the type
    string prefix without the version, e.g. ``"MyDomain.OrderPlaced"``).

    :meth:`build_chains` computes a full chain from every old version to the
    terminal (current) version and stores it for O(1) lookup at read time.
    """

    def __init__(self) -> None:
        # Edges collected before build_chains() is called.
        # {event_base_type: [(from_version, to_version, upcaster_cls), ...]}
        self._edges: dict[str, list[tuple[str, str, type]]] = {}

        # Populated by build_chains():
        # {(event_base_type, from_version): [upcaster_instance, ...]}
        self._chains: dict[tuple[str, str], list[Any]] = {}

        # {old_type_string: current_event_class}
        self._version_map: dict[str, type] = {}

    # ------------------------------------------------------------------
    # Registration (called during domain init, before build_chains)
    # ------------------------------------------------------------------

    def register_upcaster(
        self,
        event_base_type: str,
        from_version: str,
        to_version: str,
        upcaster_cls: type,
    ) -> None:
        """Record a single upcaster edge for later chain construction."""
        self._edges.setdefault(event_base_type, []).append(
            (from_version, to_version, upcaster_cls)
        )

    # ------------------------------------------------------------------
    # Chain building (called once during domain.init())
    # ------------------------------------------------------------------

    def build_chains(self, events_and_commands: dict[str, type]) -> None:
        """Build and validate all upcaster chains from registered edges.

        Also populates :attr:`_version_map` so that old type strings can be
        resolved to the current event class.

        Raises :class:`ConfigurationError` on:
        - Duplicate upcasters for the same ``(event_type, from_version)``
        - Cycles in the version graph
        - Non-convergent chains (multiple terminal versions)
        - Chains that do not reach the current ``__version__``
        """
        if not self._edges:
            return

        for event_base_type, edges in self._edges.items():
            self._build_chain_for_event(event_base_type, edges, events_and_commands)

        # Edges are no longer needed after building.
        self._edges.clear()

    def _build_chain_for_event(
        self,
        event_base_type: str,
        edges: list[tuple[str, str, type]],
        events_and_commands: dict[str, type],
    ) -> None:
        # Build adjacency map: from_version → (to_version, upcaster_cls)
        adjacency: dict[str, tuple[str, type]] = {}
        all_from: set[str] = set()
        all_to: set[str] = set()

        for from_v, to_v, cls in edges:
            if from_v in adjacency:
                existing = adjacency[from_v]
                raise ConfigurationError(
                    f"Duplicate upcaster for `{event_base_type}` "
                    f"from version `{from_v}`: "
                    f"`{existing[1].__name__}` (→ {existing[0]}) and "
                    f"`{cls.__name__}` (→ {to_v})"
                )
            adjacency[from_v] = (to_v, cls)
            all_from.add(from_v)
            all_to.add(to_v)

        # Terminal version: appears as a *to* but never as a *from*.
        terminal_versions = all_to - all_from
        if len(terminal_versions) != 1:
            raise ConfigurationError(
                f"Upcaster chain for `{event_base_type}` does not converge "
                f"to a single current version. "
                f"Terminal versions found: {sorted(terminal_versions)}"
            )
        current_version = terminal_versions.pop()

        # Verify the terminal version matches a registered event class.
        current_type_string = f"{event_base_type}.{current_version}"
        current_cls = events_and_commands.get(current_type_string)
        if current_cls is None:
            raise ConfigurationError(
                f"Upcaster chain for `{event_base_type}` targets version "
                f"`{current_version}`, but no event is registered with type "
                f"string `{current_type_string}`"
            )

        # Walk from each source version to the terminal, building the chain.
        for start_version in all_from:
            chain: list[Any] = []
            visited: set[str] = set()
            v = start_version

            while v in adjacency:
                if v in visited:
                    raise ConfigurationError(
                        f"Cycle detected in upcaster chain for "
                        f"`{event_base_type}` at version `{v}`"
                    )
                visited.add(v)
                to_v, upcaster_cls = adjacency[v]
                chain.append(upcaster_cls())  # instantiate once, reuse
                v = to_v

            if v != current_version:
                raise ConfigurationError(
                    f"Upcaster chain for `{event_base_type}` starting at "
                    f"`{start_version}` does not reach current version "
                    f"`{current_version}` (ends at `{v}`)"
                )

            self._chains[(event_base_type, start_version)] = chain
            self._version_map[f"{event_base_type}.{start_version}"] = current_cls

    # ------------------------------------------------------------------
    # Runtime lookup & application
    # ------------------------------------------------------------------

    def upcast(self, event_base_type: str, from_version: str, data: dict) -> dict:
        """Apply the upcaster chain and return the transformed payload.

        Returns *data* unchanged if no chain exists for the given key.
        """
        chain = self._chains.get((event_base_type, from_version))
        if not chain:
            return data

        for upcaster in chain:
            data = upcaster.upcast(data)

        return data

    def resolve_event_class(self, type_string: str) -> type | None:
        """Map an old type string to the current event class, or ``None``."""
        return self._version_map.get(type_string)

    def needs_upcasting(self, type_string: str) -> bool:
        """Return ``True`` if *type_string* requires upcasting."""
        return type_string in self._version_map
