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

    Attributes:
        strictness: How breaking changes are handled. ``"strict"`` treats them
            as errors (exit code 1), ``"warn"`` reports them and allows the
            operation, and ``"off"`` skips compatibility checking.
        exclude: Fully-qualified names of elements to leave out of the
            compatibility report. The published-event contract check ignores
            this list, so a contract break on an excluded published event
            still counts as breaking.
        min_versions_before_removal: Minimum number of minor versions a
            deprecated element or field must survive before it can be removed.
        staleness_enabled: Whether the staleness check is active.
        domains: Logical domain names mapped to module paths, from the
            ``[domains]`` section of ``config.toml``. When non-empty, hooks
            run over every domain in it.

    Raises:
        ValueError: If ``strictness`` is not one of the three values,
            ``min_versions_before_removal`` is not a positive integer,
            ``staleness_enabled`` is not a bool, or ``domains`` is not a dict.
    """

    strictness: str = "strict"
    exclude: tuple[str, ...] = ()
    min_versions_before_removal: int = 3
    staleness_enabled: bool = True
    domains: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Check the type first: an unhashable value such as a TOML array would
        # raise TypeError from the set membership test below.
        if (
            not isinstance(self.strictness, str)
            or self.strictness not in _STRICTNESS_VALUES
        ):
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
    compat = _require_table(data.get("compatibility", {}), "compatibility")
    staleness = _require_table(data.get("staleness", {}), "staleness")
    deprecation = _require_table(
        compat.get("deprecation", {}), "compatibility.deprecation"
    )

    kwargs: dict[str, Any] = {}

    if "strictness" in compat:
        kwargs["strictness"] = compat["strictness"]

    if "exclude" in compat:
        kwargs["exclude"] = _parse_exclude(compat["exclude"])

    if "min_versions_before_removal" in deprecation:
        kwargs["min_versions_before_removal"] = _parse_min_versions(
            deprecation["min_versions_before_removal"]
        )

    if "enabled" in staleness:
        kwargs["staleness_enabled"] = _parse_staleness_enabled(staleness["enabled"])

    # Parse [domains] section — maps logical names to module paths
    domains = _parse_domains(data.get("domains", {}))
    if domains:
        kwargs["domains"] = domains

    return CompatConfig(**kwargs)


def _require_table(value: Any, name: str) -> dict[str, Any]:
    """Return *value* if it is a TOML table, else raise ``ValueError``."""
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a TOML table, not " + type(value).__name__)
    return value


def _parse_exclude(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(e, str) for e in value):
        raise ValueError("compatibility.exclude must be a list of strings")
    return tuple(value)


def _parse_min_versions(value: Any) -> int:
    if not isinstance(value, int) or value < 1:
        raise ValueError(
            "compatibility.deprecation.min_versions_before_removal "
            "must be a positive integer"
        )
    return value


def _parse_staleness_enabled(value: Any) -> bool:
    if not isinstance(value, bool):
        raise ValueError("staleness.enabled must be a boolean")
    return value


def _parse_domains(value: Any) -> dict[str, str]:
    """Return a copy of the ``[domains]`` table, or raise ``ValueError``."""
    domains = _require_table(value, "domains")
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in domains.items()):
        raise ValueError(
            'domains entries must be string key-value pairs (name = "module.path")'
        )
    return dict(domains)
