"""A pytest plugin that writes the markers of every collected test to a file.

Load it with ``-p tests.support.adapter_markers`` and set ``MARKERS_FILE`` to
the output path. When collection finishes, the plugin writes a JSON object that
maps each test's node ID to two sorted lists:

- ``markers``: the names of its markers, including those from
  ``pytest.param(..., marks=...)``. ``-m`` selects on these.
- ``keywords``: its keywords that are registered marker names, such as the
  name of a parent ``redis/`` folder. ``tests/conftest.py`` skips an opt-in
  test by keyword, so a test under ``redis/`` needs ``--redis`` even without
  the ``redis`` marker.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

MARKERS_FILE = "MARKERS_FILE"


def pytest_collection_finish(session: pytest.Session) -> None:
    registered = {
        line.split(":")[0].strip() for line in session.config.getini("markers")
    }
    markers = {
        item.nodeid: {
            "markers": sorted({mark.name for mark in item.iter_markers()}),
            "keywords": sorted(k for k in item.keywords if k in registered),
        }
        for item in session.items
    }
    Path(os.environ[MARKERS_FILE]).write_text(json.dumps(markers), encoding="utf-8")
