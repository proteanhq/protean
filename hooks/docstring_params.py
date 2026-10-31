"""Fail the build when a docstring documents a parameter its signature lacks.

Griffe logs this as a warning while mkdocstrings renders the API pages. The
build runs without ``--strict``, so on its own the warning never fails it, and
a renamed or removed parameter leaves its old description on the published page.
This hook collects those warnings and fails the build once it finishes.
"""

from __future__ import annotations

import logging
from typing import Any

from mkdocs.exceptions import PluginError

MARKER = "does not appear in the function signature"


class _Collector(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        if MARKER in message:
            self.messages.append(message)


collector = _Collector()


def on_config(config: Any) -> None:
    # mkdocstrings logs griffe's warnings under the `mkdocs` logger, which does
    # not propagate to the root logger. `mkdocs serve` reloads the config on
    # every rebuild, so start each build empty and attach the handler once.
    collector.messages.clear()
    mkdocs_logger = logging.getLogger("mkdocs")
    if collector not in mkdocs_logger.handlers:
        mkdocs_logger.addHandler(collector)


def on_post_build(config: Any) -> None:
    if collector.messages:
        found = "\n".join(f"  {message}" for message in collector.messages)
        raise PluginError(
            f"Docstrings document parameters their signatures do not have:\n{found}"
        )
