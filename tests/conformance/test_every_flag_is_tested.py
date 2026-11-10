"""Every capability flag of a port gates at least one conformance test.

Each port's suite joins ``SUITES`` when it moves under ``tests/conformance/``.
Until then the one entry is a synthetic flag with a synthetic suite, which
proves the check itself.
"""

from collections.abc import Callable
from enum import Flag, auto
from pathlib import Path

import pytest

from tests.conformance.flag_coverage import collect_items, untested_flags


class SyntheticCapabilities(Flag):
    ALPHA = auto()
    BETA = auto()
    GAMMA = auto()
    DELTA = auto()
    TIER = ALPHA | BETA


SYNTHETIC_SUITE = """
import pytest

from tests.conformance.test_every_flag_is_tested import SyntheticCapabilities as Caps


@pytest.mark.requires(Caps.ALPHA)
def test_alpha():
    pass


@pytest.mark.requires(Caps.BETA, Caps.GAMMA)
def test_beta_and_gamma():
    pass


class TestDelta:
    @pytest.mark.requires_any(Caps.DELTA, Caps.ALPHA)
    def test_delta_or_alpha(self):
        pass


def test_ungated():
    pass
"""


def write_synthetic_suite(folder: Path) -> Path:
    path = folder / "test_synthetic_suite.py"
    path.write_text(SYNTHETIC_SUITE)
    return path


# Each port's flag type and a function that returns its suite's path, given a
# scratch folder to write a suite into.
SUITES: list[tuple[type[Flag], Callable[[Path], Path]]] = [
    (SyntheticCapabilities, write_synthetic_suite),
]


@pytest.mark.parametrize(
    "flag_type, suite", SUITES, ids=[flags.__name__ for flags, _ in SUITES]
)
def test_every_flag_gates_a_test(request, tmp_path, flag_type, suite):
    items = collect_items(request.session, suite(tmp_path))

    assert items
    assert untested_flags(flag_type, items) == []


# The suites below are imported into this session by file name, so each one
# needs a file name no other test module in the session uses.


class TestUntestedFlags:
    def test_reports_a_flag_no_marker_names(self, request, tmp_path):
        path = tmp_path / "test_partial_suite.py"
        path.write_text(
            SYNTHETIC_SUITE.replace(
                "@pytest.mark.requires_any(Caps.DELTA, Caps.ALPHA)",
                "@pytest.mark.requires(Caps.ALPHA)",
            )
        )

        items = collect_items(request.session, path)

        assert untested_flags(SyntheticCapabilities, items) == [
            SyntheticCapabilities.DELTA
        ]

    def test_a_tier_marker_covers_its_flags(self, request, tmp_path):
        path = tmp_path / "test_tier_suite.py"
        path.write_text(
            "import pytest\n"
            "from tests.conformance.test_every_flag_is_tested import "
            "SyntheticCapabilities as Caps\n\n"
            "@pytest.mark.requires(Caps.TIER)\n"
            "def test_tier():\n"
            "    pass\n"
        )

        items = collect_items(request.session, path)

        assert untested_flags(SyntheticCapabilities, items) == [
            SyntheticCapabilities.GAMMA,
            SyntheticCapabilities.DELTA,
        ]

    def test_a_union_marker_covers_its_flags(self, request, tmp_path):
        path = tmp_path / "test_union_suite.py"
        path.write_text(
            "import pytest\n"
            "from tests.conformance.test_every_flag_is_tested import "
            "SyntheticCapabilities as Caps\n\n"
            "@pytest.mark.requires(Caps.GAMMA | Caps.DELTA)\n"
            "def test_union():\n"
            "    pass\n"
        )

        items = collect_items(request.session, path)

        assert untested_flags(SyntheticCapabilities, items) == [
            SyntheticCapabilities.ALPHA,
            SyntheticCapabilities.BETA,
        ]

    def test_collects_every_test_file_in_a_folder(self, request, tmp_path):
        (tmp_path / "test_folder_suite.py").write_text(SYNTHETIC_SUITE)
        (tmp_path / "nested").mkdir()
        (tmp_path / "nested" / "test_nested_suite.py").write_text(
            "def test_nested():\n    pass\n"
        )

        items = collect_items(request.session, tmp_path)

        assert sorted(item.name for item in items) == [
            "test_alpha",
            "test_beta_and_gamma",
            "test_delta_or_alpha",
            "test_nested",
            "test_ungated",
        ]
