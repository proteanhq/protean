"""IR compatibility configuration — load `.protean/config.toml`.

Provides a ``CompatConfig`` dataclass and a ``load_config()`` loader that
reads the optional ``.protean/config.toml`` file.  When no config file
exists, sensible defaults are used.

Usage::

    from protean.ir.config import load_config

    config = load_config(".protean")
    if config.strictness == "off":
        ...  # skip compatibility checking
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "CompatConfig",
    "load_config",
]

_CONFIG_FILENAME = "config.toml"

# Valid values for ``strictness``
_STRICTNESS_VALUES = frozenset({"strict", "warn", "off"})


@dataclass(frozen=True)
class CompatConfig:
    """Configuration for IR compatibility checking.

    Attributes
    ----------
    strictness:
        Controls how breaking changes are handled:
        - ``"strict"`` — treat breaking changes as errors (exit code 1).
        - ``"warn"`` — report breaking changes but allow the operation.
        - ``"off"`` — skip compatibility checking entirely.
    exclude:
        Fully-qualified names of elements to exclude from compatibility checks.
    min_versions_before_removal:
        Minimum number of minor versions a deprecated element/field must
        survive before it can be removed.
    staleness_enabled:
        Whether the staleness check is active.
    domains:
        Mapping of logical domain names to module paths, parsed from the
        ``[domains]`` section of ``config.toml``.  When non-empty, hooks
        iterate over all domains automatically.
    """

    strictness: str = "strict"
    exclude: tuple[str, ...] = ()
    min_versions_before_removal: int = 3
    staleness_enabled: bool = True
    domains: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.strictness not in _STRICTNESS_VALUES:
            raise ValueError(
                f"Invalid strictness value: {self.strictness!r}. "
                f"Must be one of: {', '.join(sorted(_STRICTNESS_VALUES))}"
            )
        if (
            not isinstance(self.min_versions_before_removal, int)
            or self.min_versions_before_removal < 1
        ):
            raise ValueError("min_versions_before_removal must be a positive integer")
        if not isinstance(self.staleness_enabled, bool):
            raise ValueError("staleness_enabled must be a boolean")
        if not isinstance(self.domains, dict):
            raise ValueError("domains must be a mapping of name → module path")

    def is_excluded(self, fqn: str) -> bool:
        """Return ``True`` if *fqn* matches any entry in ``exclude``."""
        return fqn in self.exclude


def load_config(protean_dir: Path | str = ".protean") -> CompatConfig:
    """Load compatibility config from *protean_dir*/config.toml.

    Returns a ``CompatConfig`` populated from the TOML file.  When the
    file does not exist, default values are used.

    Raises :exc:`ValueError` if the file exists but is malformed or
    contains invalid values.
    """
    config_path = Path(protean_dir) / _CONFIG_FILENAME

    if not config_path.exists():
        return CompatConfig()

    try:
        raw = config_path.read_bytes()
    except OSError as exc:
        raise ValueError(f"Could not read {config_path}: {exc}") from exc

    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"Invalid TOML in {config_path}: {exc}") from exc

    return _parse_config(data)


def _parse_config(data: dict[str, Any]) -> CompatConfig:
    """Build a ``CompatConfig`` from parsed TOML data."""
    compat = data.get("compatibility", {})
    if not isinstance(compat, dict):
        raise ValueError(
            "compatibility must be a TOML table, not " + type(compat).__name__
        )

    staleness = data.get("staleness", {})
    if not isinstance(staleness, dict):
        raise ValueError(
            "staleness must be a TOML table, not " + type(staleness).__name__
        )

    deprecation = compat.get("deprecation", {})
    if not isinstance(deprecation, dict):
        raise ValueError(
            "compatibility.deprecation must be a TOML table, not "
            + type(deprecation).__name__
        )

    kwargs: dict[str, Any] = {}

    if "strictness" in compat:
        kwargs["strictness"] = compat["strictness"]

    if "exclude" in compat:
        exclude = compat["exclude"]
        if not isinstance(exclude, list) or not all(
            isinstance(e, str) for e in exclude
        ):
            raise ValueError("compatibility.exclude must be a list of strings")
        kwargs["exclude"] = tuple(exclude)

    if "min_versions_before_removal" in deprecation:
        val = deprecation["min_versions_before_removal"]
        if not isinstance(val, int) or val < 1:
            raise ValueError(
                "compatibility.deprecation.min_versions_before_removal "
                "must be a positive integer"
            )
        kwargs["min_versions_before_removal"] = val

    if "enabled" in staleness:
        val = staleness["enabled"]
        if not isinstance(val, bool):
            raise ValueError("staleness.enabled must be a boolean")
        kwargs["staleness_enabled"] = val

    # Parse [domains] section — maps logical names to module paths
    domains_raw = data.get("domains", {})
    if not isinstance(domains_raw, dict):
        raise ValueError(
            "domains must be a TOML table, not " + type(domains_raw).__name__
        )
    if domains_raw:
        if not all(
            isinstance(k, str) and isinstance(v, str) for k, v in domains_raw.items()
        ):
            raise ValueError(
                'domains entries must be string key-value pairs (name = "module.path")'
            )
        kwargs["domains"] = dict(domains_raw)

    return CompatConfig(**kwargs)
