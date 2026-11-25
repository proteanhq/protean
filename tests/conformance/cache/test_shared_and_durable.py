"""Entries seen by a second adapter, and entries kept after an adapter closes.

Each test builds its own adapters from the configuration under test. The extra
adapters use the name of the plugin's adapter, `default`, because SHARED and
DURABLE promise the entries to an adapter built from the same config.

The SHARED test leaves the plugin's adapter open. The DURABLE test closes it
after the writer's write succeeds, so no adapter from the config is open when
the reader is built. The test then makes the reader the domain's default cache, and the
plugin clears and closes the reader after the test.
"""

from typing import Any

import pytest

from protean.domain import Domain
from protean.infra.cache import Cache
from protean.infra.registry import caches
from protean.port.cache import CacheCapabilities, CachePort


def _build(name: str, domain: Domain, config: dict[str, Any]) -> CachePort:
    return caches.get(config["provider"])(name, domain, dict(config))


@pytest.mark.requires(CacheCapabilities.KEY_VALUE, CacheCapabilities.SHARED)
def test_a_second_adapter_from_the_same_config_reads_the_first_ones_writes(
    adapter, adapter_config, test_domain
):
    second = _build("default", test_domain, adapter_config)
    try:
        adapter.put("shared:::1", {"value": "one"}, 60.0)

        assert second.get("shared:::1") == {"value": "one"}
    finally:
        second.close()


@pytest.mark.requires(CacheCapabilities.KEY_VALUE, CacheCapabilities.DURABLE)
def test_an_entry_outlasts_the_adapter_that_wrote_it(
    adapter, adapter_config, test_domain
):
    writer = _build("default", test_domain, adapter_config)
    try:
        writer.put("durable:::1", {"value": "one"}, 60.0)
    finally:
        writer.close()
    # Closed only after the write succeeds: when `put` raises, the plugin's
    # adapter stays open, and the plugin clears and closes it after the test.
    adapter.close()

    reader = _build("default", test_domain, adapter_config)
    # The plugin clears and closes the domain's default cache after the test.
    # Pointing it at the reader before the assertion means a failed read still
    # clears the backend. If building the reader raises, the plugin clears its
    # own closed adapter, which takes a constructor that rejects the config it
    # accepted for the writer.
    test_domain.caches["default"] = Cache(reader)

    assert reader.get("durable:::1") == {"value": "one"}
