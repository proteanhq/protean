import logging

from protean.exceptions import IncorrectUsageError, NotSupportedError
from protean.utils import DomainObjects, derive_element_class
from protean.utils.container import Element, OptionsMixin
from protean.utils.mixins import HandlerMixin

logger = logging.getLogger(__name__)


class BaseEventHandler(Element, HandlerMixin, OptionsMixin):
    """Base Event Handler to be inherited by all event handlers"""

    element_type = DomainObjects.EVENT_HANDLER

    def __new__(cls, *args, **kwargs):
        if cls is BaseEventHandler:
            raise NotSupportedError("BaseEventHandler cannot be instantiated")
        return super().__new__(cls)

    @classmethod
    def _default_options(cls):
        part_of = (
            getattr(cls.meta_, "part_of") if hasattr(cls.meta_, "part_of") else None
        )

        return [
            ("part_of", None),
            ("source_stream", None),
            ("stream_category", part_of.meta_.stream_category if part_of else None),
        ]


def event_handler_factory(element_cls, domain, **opts):
    element_cls = derive_element_class(element_cls, BaseEventHandler, **opts)

    if not (element_cls.meta_.part_of or element_cls.meta_.stream_category):
        raise IncorrectUsageError(
            f"Event Handler `{element_cls.__name__}` needs to be associated with an aggregate or a stream"
        )

    return element_cls
