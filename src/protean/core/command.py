from protean.container import BaseContainer, OptionsMixin
from protean.exceptions import InvalidDataError, ValidationError
from protean.fields import Field
from protean.reflection import _ID_FIELD_NAME, declared_fields
from protean.utils import DomainObjects, derive_element_class


class BaseCommand(BaseContainer, OptionsMixin):
    """Base Command class that all commands should inherit from.

    Core functionality associated with commands, like timestamping and authentication, are specified
    as part of the base command class.
    """

    element_type = DomainObjects.COMMAND

    class Meta:
        abstract = True

    def __init_subclass__(subclass) -> None:
        super().__init_subclass__()

        if not subclass.meta_.abstract:
            subclass.__track_id_field()

    def __init__(self, *args, **kwargs):
        try:
            super().__init__(*args, **kwargs)
        except ValidationError as exception:
            raise InvalidDataError(exception.messages)

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


def command_factory(element_cls, **kwargs):
    element_cls = derive_element_class(element_cls, BaseCommand, **kwargs)

    return element_cls
