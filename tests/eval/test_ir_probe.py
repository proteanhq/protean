"""Unit tests for the IR probe: the no-domain build result and IR decoding.

These do not scaffold a project (that is covered by ``test_gold``/``test_compare``
building a real gold). They cover the branches those integration tests skip: a
project with no discoverable domain, and the stdout decoder that picks the IR out
of a produced project's other prints.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.eval.ir_probe import _decode_ir, build_ir

pytestmark = pytest.mark.no_test_domain


def test_build_ir_returns_empty_for_a_project_with_no_domain(tmp_path: Path) -> None:
    """A directory with no root ``domain.py`` and no ``src/<pkg>/domain.py`` has no
    discoverable domain, so ``build_ir`` returns ``{}`` (the scorer's "no
    recoverable structure" result) without shelling out."""
    assert build_ir(tmp_path) == {}


class TestDecodeIr:
    def test_picks_the_ir_over_a_print_after_it(self) -> None:
        """The IR is the object carrying ``elements``. A stray print at teardown
        (an ``atexit`` line, a ``__del__``) lands after the IR, so the decoder
        must not return that trailing object."""
        ir = {"elements": {"AGGREGATE": []}, "clusters": {}}
        stdout = json.dumps(ir) + "\n" + json.dumps({"debug": 1}) + "\n"
        assert _decode_ir(stdout) == ir

    def test_picks_the_ir_over_a_print_before_it(self) -> None:
        """A stray import log before the IR does not win over it either."""
        ir = {"elements": {"COMMAND": ["app.commands.PlaceOrder"]}, "clusters": {}}
        stdout = json.dumps({"log": "loading"}) + "\n" + json.dumps(ir) + "\n"
        assert _decode_ir(stdout) == ir

    def test_no_json_object_decodes_to_empty(self) -> None:
        assert _decode_ir("no json here\n") == {}
        assert _decode_ir("") == {}

    def test_falls_back_to_the_last_object_when_none_carry_elements(self) -> None:
        """When no object looks like an IR (none has ``elements``), the last
        top-level object is returned as the best available."""
        stdout = json.dumps({"a": 1}) + "\n" + json.dumps({"b": 2}) + "\n"
        assert _decode_ir(stdout) == {"b": 2}
