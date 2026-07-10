"""``is_fact_event`` is framework-internal (#1107).

It remains present on ``meta_`` (defaulting to ``False``) so every read site
keeps working, but user code may not set it directly — the framework assigns it
only during fact-event generation. Passing it to an event or command through the
decorator or ``domain.register`` raises ``ConfigurationError``.
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.event import BaseEvent
from protean.exceptions import ConfigurationError
from protean.fields import Identifier, String


class User(BaseAggregate):
    name: String()


class TestIsFactEventRejected:
    def test_register_event_with_is_fact_event_raises(self, test_domain):
        class SomeEvent(BaseEvent):
            id: Identifier(identifier=True)
            name: String()

        with pytest.raises(ConfigurationError) as exc:
            test_domain.register(SomeEvent, part_of=User, is_fact_event=True)

        assert "is_fact_event" in str(exc.value)
        assert "framework" in str(exc.value)

    def test_event_decorator_with_is_fact_event_raises(self, test_domain):
        with pytest.raises(ConfigurationError) as exc:

            @test_domain.event(part_of=User, is_fact_event=True)
            class SomeEvent(BaseEvent):
                id: Identifier(identifier=True)
                name: String()

        assert "is_fact_event" in str(exc.value)

    def test_register_command_with_is_fact_event_raises(self, test_domain):
        class SomeCommand(BaseCommand):
            id: Identifier(identifier=True)
            name: String()

        with pytest.raises(ConfigurationError) as exc:
            test_domain.register(SomeCommand, part_of=User, is_fact_event=True)

        assert "is_fact_event" in str(exc.value)


class TestIsFactEventDefaultPreserved:
    def test_normal_event_has_is_fact_event_false(self, test_domain):
        class SomeEvent(BaseEvent):
            id: Identifier(identifier=True)
            name: String()

        test_domain.register(SomeEvent, part_of=User)
        test_domain.init(traverse=False)

        assert SomeEvent.meta_.is_fact_event is False

    def test_generated_fact_event_has_is_fact_event_true(self, test_domain):
        test_domain.register(User, fact_events=True)
        test_domain.init(traverse=False)

        event_records = test_domain.registry._elements["EVENT"]
        fact_events = [
            r.cls for r in event_records.values() if r.cls.meta_.is_fact_event
        ]
        assert len(fact_events) >= 1
        for fact_event in fact_events:
            assert fact_event.meta_.is_fact_event is True
