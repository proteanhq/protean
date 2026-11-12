"""Rebuilding a cache-backed projection whose cache cannot match patterns.

The rebuild removes the projection's entries by pattern before it replays any
event, so a cache without `CacheCapabilities.PATTERN_MATCH` stops it there.
"""

import pytest

from protean import current_domain
from protean.core.projector import BaseProjector, on
from protean.exceptions import NotSupportedError
from protean.infra.registry import caches as cache_registry
from tests.cache.test_cache_service import KeyValueCache

from .elements import CachedSummary, Registered, User

handled: list[str] = []


class RecordingProjector(BaseProjector):
    @on(Registered)
    def on_registered(self, event: Registered):
        handled.append(event.user_id)
        current_domain.cache_for(CachedSummary).add(
            CachedSummary(user_id=event.user_id, name=event.name)
        )


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    cache_registry.register(
        "key_value_only", f"{KeyValueCache.__module__}.{KeyValueCache.__qualname__}"
    )
    test_domain.config["caches"]["plain"] = {"provider": "key_value_only"}
    test_domain.register(User)
    test_domain.register(Registered, part_of=User)
    test_domain.register(CachedSummary, cache="plain")
    test_domain.register(
        RecordingProjector, projector_for=CachedSummary, aggregates=[User]
    )
    test_domain.init(traverse=False)
    yield
    handled.clear()
    cache_registry._paths.pop("key_value_only", None)


def test_rebuild_raises_before_any_event_is_replayed(test_domain):
    user = User.register(email="ada@example.com", name="Ada")
    current_domain.repository_for(User).add(user)
    assert handled == [user.id]
    handled.clear()

    with pytest.raises(NotSupportedError) as exc:
        test_domain.rebuild_projection(CachedSummary)

    assert "CacheCapabilities.PATTERN_MATCH" in str(exc.value)
    assert handled == []
