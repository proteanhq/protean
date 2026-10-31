"""`hooks/docstring_params.py`, the mkdocs hook that fails the docs build when a
docstring documents a parameter its signature does not have.
"""

from __future__ import annotations

import importlib.util
import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("mkdocs")

from mkdocs.exceptions import PluginError

REPO = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "docstring_params_hook", REPO / "hooks" / "docstring_params.py"
)
assert _spec is not None and _spec.loader is not None
hook = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hook)

pytestmark = pytest.mark.no_test_domain

STALE = (
    "src/protean/core/value_object.py:407: "
    "Parameter 'bogus_param' does not appear in the function signature"
)


@pytest.fixture(autouse=True)
def _restore_loggers() -> Iterator[None]:
    mkdocs_logger = logging.getLogger("mkdocs")
    griffe_logger = logging.getLogger("mkdocs.plugins.griffe")
    levels = (mkdocs_logger.level, griffe_logger.level)
    yield
    griffe_logger.removeHandler(hook.collector)
    mkdocs_logger.setLevel(levels[0])
    griffe_logger.setLevel(levels[1])


def test_a_stale_parameter_fails_the_build() -> None:
    hook.on_config({})
    logging.getLogger("mkdocs.plugins.griffe").warning(STALE)

    with pytest.raises(PluginError, match="bogus_param"):
        hook.on_post_build({})


def test_a_quiet_build_still_fails_on_a_stale_parameter() -> None:
    # `mkdocs build -q` sets the `mkdocs` logger to ERROR before hooks load.
    logging.getLogger("mkdocs").setLevel(logging.ERROR)
    hook.on_config({})
    logging.getLogger("mkdocs.plugins.griffe").warning(STALE)

    with pytest.raises(PluginError, match="bogus_param"):
        hook.on_post_build({})


def test_other_griffe_warnings_do_not_fail_the_build() -> None:
    hook.on_config({})
    logging.getLogger("mkdocs.plugins.griffe").warning(
        "src/protean/core/value_object.py:407: "
        "No type or annotation for parameter 'bogus_param'"
    )

    hook.on_post_build({})


def test_each_build_starts_with_no_findings() -> None:
    hook.on_config({})
    logging.getLogger("mkdocs.plugins.griffe").warning(STALE)
    hook.on_config({})

    hook.on_post_build({})
