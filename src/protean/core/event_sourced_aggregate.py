import logging

from protean.container import BaseContainer, OptionsMixin
from protean.utils import DomainObjects, derive_element_class
from protean.utils import inflection

logger = logging.getLogger("protean.event")


class BaseEventSourcedAggregate(BaseContainer, OptionsMixin):
    """Base Event Sourced Aggregate class that all EventSourced Aggregates should inherit from.
    """

    element_type = DomainObjects.EVENT_SOURCED_AGGREGATE

    class Meta:
        abstract = True

    @classmethod
    def _default_options(cls):
        return [
            ("stream_name", inflection.underscore(cls.__name__)),
        ]


def event_sourced_aggregate_factory(element_cls, **opts):
    return derive_element_class(element_cls, BaseEventSourcedAggregate, **opts)
