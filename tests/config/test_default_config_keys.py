"""Every top-level config key the framework reads is in ``_default_config()``.

``Config2._normalize_config`` keeps only the top-level keys listed in
``_default_config()`` and drops the rest without a warning. A key read by the
framework but missing from the defaults cannot be set at the top level of
``domain.toml``, ``pyproject.toml`` or a ``config=`` dict. This test scans ``src/protean`` for
reads on a domain's config and checks each key against the defaults.
"""

import re
from pathlib import Path

import protean
from protean.domain.config import _default_config

_SRC = Path(protean.__file__).parent

# User-facing skill examples, not framework code.
_EXCLUDED = _SRC / "dx" / "pack"

# Reads of a top-level key on a domain's config, for example
# ``domain.config.get("lint", {})`` or ``self._domain.config["databases"]``.
# The receiver is anchored: a bare ``config.get(...)`` is often a nested
# section (``telemetry``, a subscription config), whose keys are not top-level.
_READ = re.compile(
    r"\b(?:domain|self|self\._domain|derived_domain|current_domain)"
    r"\.config(?:\.get\(|\[)\s*[\"']([a-z_]+)[\"']"
)


def _scan() -> dict[str, list[str]]:
    """Map each top-level key read in the framework to its ``file:line`` sites."""
    found: dict[str, list[str]] = {}
    for path in sorted(_SRC.rglob("*.py")):
        if path.is_relative_to(_EXCLUDED):
            continue
        # Match over the whole file, so a read the formatter wraps across lines
        # (``config.get(\n    "lint", {}\n)``) is still found.
        text = path.read_text()
        for match in _READ.finditer(text):
            lineno = text.count("\n", 0, match.start()) + 1
            site = f"{path.relative_to(_SRC.parent)}:{lineno}"
            found.setdefault(match.group(1), []).append(site)
    return found


def test_scan_finds_known_reads():
    found = _scan()

    assert {"lint", "observatory", "databases"} <= found.keys()


def test_every_read_key_is_a_default_key():
    defaults = _default_config().keys()

    missing = {key: sites for key, sites in _scan().items() if key not in defaults}

    assert not missing, "Top-level config keys read but missing from " + (
        "_default_config(), so the loader drops them: "
        + "; ".join(f"{key!r} at {', '.join(sites)}" for key, sites in missing.items())
    )


def test_scan_finds_a_read_wrapped_across_lines(tmp_path, monkeypatch):
    module = tmp_path / "wrapped.py"
    module.write_text('value = domain.config.get(\n    "wrapped_key", {}\n)\n')
    monkeypatch.setattr(f"{__name__}._SRC", tmp_path)

    assert _scan() == {"wrapped_key": [f"{tmp_path.name}/wrapped.py:1"]}
