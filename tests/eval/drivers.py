"""The thing that produces assistant turns for a run.

A driver decides, turn by turn, what the assistant says and which tools it
calls. The run loop feeds every tool result back into the conversation the
driver sees, so a live driver can react to a failed ``run_verify``.

Two drivers matter:

- :class:`ReplayDriver` replays recorded turns with no model. It ignores the
  conversation and hands back the transcript's turns in order. This is the
  deterministic CI lane, and the same driver the bootstrap fixture is generated
  with.
- A live driver calls a real model. It is resolved at runtime from
  ``PROTEAN_EVAL_LIVE_DRIVER`` (see :func:`resolve_live_driver`), so the harness
  ships no model dependency and adds no metered API key. When the variable is
  unset the live lane skips; when it is set but wrong, resolution raises rather
  than skipping silently.
"""

from __future__ import annotations

import importlib
import os
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from tests.eval.transcript import ToolCall, Turn

__all__ = [
    "LIVE_DRIVER_ENV_VAR",
    "Conversation",
    "Driver",
    "LiveDriverError",
    "Message",
    "ReplayDriver",
    "Role",
    "resolve_live_driver",
]

LIVE_DRIVER_ENV_VAR = "PROTEAN_EVAL_LIVE_DRIVER"

# The conversation roles. A user message states the task, an assistant message
# carries text and tool calls, a tool message carries their results.
Role = Literal["user", "assistant", "tool"]


class LiveDriverError(Exception):
    """The live-driver env var is set but does not name a usable factory."""


@dataclass
class Message:
    """One conversation message. An assistant message carries text and the tool
    calls it requested; a tool message carries the results of those calls,
    aligned by position."""

    role: Role
    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_results: tuple[dict[str, Any], ...] = ()


@dataclass
class Conversation:
    """The running conversation a driver reads to decide its next turn: the pack
    guidance as the system prompt, then the ordered messages so far."""

    system_prompt: str
    messages: list[Message] = field(default_factory=list)


@runtime_checkable
class Driver(Protocol):
    """Produces the next assistant turn, or ``None`` to stop the run."""

    def next_turn(
        self, conversation: Conversation
    ) -> Turn | None: ...  # pragma: no cover


@dataclass
class ReplayDriver:
    """Replays recorded turns in order, ignoring the conversation.

    Returns ``None`` once its turns are exhausted, which ends the run. Because it
    never looks at tool results, the project a replay lands depends only on the
    recorded turns, not on any model.
    """

    turns: tuple[Turn, ...]
    _index: int = field(default=0, init=False)

    def next_turn(self, conversation: Conversation) -> Turn | None:
        if self._index >= len(self.turns):
            return None
        turn = self.turns[self._index]
        self._index += 1
        return turn


def resolve_live_driver(
    system_prompt: str, tool_specs: list[dict[str, Any]]
) -> Driver | None:
    """Resolve the live driver from ``PROTEAN_EVAL_LIVE_DRIVER``.

    The variable names a factory as ``module.path:attribute``. The factory is
    called with the pack *system_prompt* and the *tool_specs* and must return a
    :class:`Driver`. Returns ``None`` when the variable is unset, so the live
    lane skips. Raises :class:`LiveDriverError` when the variable is malformed
    or the factory returns something without a callable ``next_turn``. When the
    variable names a module or attribute that cannot be imported, that error
    propagates so a misconfigured driver fails loudly.
    """
    spec = os.environ.get(LIVE_DRIVER_ENV_VAR)
    if not spec:
        return None
    module_name, separator, attribute = spec.partition(":")
    if not separator or not module_name or not attribute:
        raise LiveDriverError(
            f"{LIVE_DRIVER_ENV_VAR} must be 'module.path:factory', got {spec!r}"
        )
    module = importlib.import_module(module_name)
    factory = getattr(module, attribute)
    if not callable(factory):
        raise LiveDriverError(
            f"{spec!r} names {factory!r}, which is not callable; it must be a "
            f"factory(system_prompt, tool_specs) -> Driver"
        )
    driver = factory(system_prompt, tool_specs)
    # A runtime-checkable Protocol confirms the attribute exists, not that it is
    # callable, so a stub like next_turn=1 would pass. Check both.
    if not isinstance(driver, Driver) or not callable(driver.next_turn):
        raise LiveDriverError(
            f"{spec!r} returned {driver!r}, which is not a Driver (no callable next_turn)"
        )
    return driver
