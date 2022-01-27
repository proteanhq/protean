import logging

from protean.container import BaseContainer, OptionsMixin
from protean.fields import Field
from protean.reflection import _ID_FIELD_NAME, declared_fields
from protean.utils import DomainObjects, derive_element_class

logger = logging.getLogger(__name__)


class BaseEvent(BaseContainer, OptionsMixin):  # FIXME Remove OptionsMixin
    """Base Event class that all Events should inherit from.

    Core functionality associated with Events, like timestamping, are specified
    as part of the base Event class.
    """

    element_type = DomainObjects.EVENT

    class Meta:
        abstract = True

    def __init_subclass__(subclass) -> None:
        super().__init_subclass__()

        if not subclass.meta_.abstract:
            subclass.__track_id_field()

    @classmethod
    def _default_options(cls):
        return [("aggregate_cls", None), ("stream_name", None)]

    @classmethod
    def __track_id_field(subclass):
        """Check if an identifier field has been associated with the command.

        When an identifier is provided, its value is used to construct
        unique stream name."""
        if declared_fields(subclass):
            try:
                id_field = next(
                    field
                    for _, field in declared_fields(subclass).items()
                    if isinstance(field, (Field)) and field.identifier
                )

                setattr(subclass, _ID_FIELD_NAME, id_field.field_name)

            except StopIteration:
                # No Identity fields declared
                pass


def domain_event_factory(element_cls, **kwargs):
    return derive_element_class(element_cls, BaseEvent, **kwargs)
