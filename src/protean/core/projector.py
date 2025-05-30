from protean.exceptions import IncorrectUsageError, NotSupportedError
from protean.utils import DomainObjects, derive_element_class
from protean.utils.container import Element, OptionsMixin
from protean.utils.mixins import HandlerMixin, handle


class BaseProjector(Element, HandlerMixin, OptionsMixin):
    """Base class for all Projectors. This is also a marker class that is referenced
    when projectors are registered with the domain.

    Projectors are used to project events into projections.
    """

    element_type = DomainObjects.PROJECTOR

    @classmethod
    def _default_options(cls):
        projector_for = (
            getattr(cls.meta_, "projector_for")
            if hasattr(cls.meta_, "projector_for")
            else None
        )

        # Use aggregates if specified, otherwise default to empty list
        aggregates = (
            getattr(cls.meta_, "aggregates") if hasattr(cls.meta_, "aggregates") else []
        )

        # Use stream categories if specified. Otherwise,
        #   If aggregates are specified, gather stream categories from each aggregate
        #   If no stream categories nor aggregates are specified, default to empty list
        #   If both are specified, use stream categories
        stream_categories = (
            getattr(cls.meta_, "stream_categories")
            if hasattr(cls.meta_, "stream_categories")
            else []
        )

        # If aggregates are specified and stream categories are not, gather stream categories from each aggregate
        if aggregates and not stream_categories:
            stream_categories = [
                aggregate.meta_.stream_category for aggregate in aggregates
            ]

        return [
            ("projector_for", projector_for),
            ("aggregates", aggregates),
            ("stream_categories", stream_categories),
        ]

    def __new__(cls, *args, **kwargs):
        if cls is BaseProjector:
            raise NotSupportedError("BaseProjector cannot be instantiated")
        return super().__new__(cls)


def projector_factory(element_cls, domain, **opts):
    element_cls = derive_element_class(element_cls, BaseProjector, **opts)

    if not element_cls.meta_.projector_for:
        raise IncorrectUsageError(
            f"Projector `{element_cls.__name__}` needs to be associated with a Projection"
        )

    # Throw error if neither aggregates nor stream categories are specified
    if not (element_cls.meta_.aggregates or element_cls.meta_.stream_categories):
        raise IncorrectUsageError(
            f"Projector `{element_cls.__name__}` needs to be associated with at least one Aggregate or Stream Category"
        )

    return element_cls


# `on` is a shortcut for `handle` in the context of projectors
on = handle
