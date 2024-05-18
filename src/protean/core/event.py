import logging

from protean.container import BaseContainer, OptionsMixin
from protean.exceptions import IncorrectUsageError
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

    def __init__(self, *args, **kwargs):
        # Set the flag to prevent any further modifications
        self._initialized = False

        super().__init__(*args, **kwargs)

        # If we made it this far, the Value Object is initialized
        #   and should be marked as such
        self._initialized = True

    def __setattr__(self, name, value):
        if not hasattr(self, "_initialized") or not self._initialized:
            return super().__setattr__(name, value)
        else:
            raise IncorrectUsageError(
                {
                    "_event": [
                        "Event Objects are immutable and cannot be modified once created"
                    ]
                }
            )

    @classmethod
    def _default_options(cls):
        return [("abstract", False), ("part_of", None), ("stream_name", None)]

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
    element_cls = derive_element_class(element_cls, BaseEvent, **kwargs)

    if (
        not (element_cls.meta_.part_of or element_cls.meta_.stream_name)
        and not element_cls.meta_.abstract
    ):
        raise IncorrectUsageError(
            {
                "_event": [
                    f"Event `{element_cls.__name__}` needs to be associated with an aggregate or a stream"
                ]
            }
        )

    return element_cls
