"""Value Object Functionality and Classes"""

import logging

from collections import defaultdict

from protean.container import BaseContainer, OptionsMixin, fields
from protean.exceptions import IncorrectUsageError, NotSupportedError, ValidationError
from protean.fields import Reference, ValueObject
from protean.fields.association import Association
from protean.utils import DomainObjects, derive_element_class

logger = logging.getLogger(__name__)


class BaseValueObject(BaseContainer, OptionsMixin):
    element_type = DomainObjects.VALUE_OBJECT

    class Meta:
        abstract = True

    def __init_subclass__(subclass) -> None:
        super().__init_subclass__()

        subclass.__validate_for_basic_field_types()

    @classmethod
    def __validate_for_basic_field_types(subclass):
        for field_name, field_obj in fields(subclass).items():
            if isinstance(field_obj, (Reference, Association, ValueObject)):
                raise IncorrectUsageError(
                    {
                        "_entity": [
                            f"Views can only contain basic field types. "
                            f"Remove {field_name} ({field_obj.__class__.__name__}) from class {subclass.__name__}"
                        ]
                    }
                )

    def __init__(self, *template, **kwargs):  # noqa: C901
        """
        Initialise the container.

        During initialization, set value on fields if validation passes.

        This initialization technique supports keyword arguments as well as dictionaries. You
            can even use a template for initial data.

        FIXME Can we depend on Container's Init and only implement VO specific aspects here?
        """

        if self.meta_.abstract is True:
            raise NotSupportedError(
                f"{self.__class__.__name__} class has been marked abstract"
                f" and cannot be instantiated"
            )

        self.errors = defaultdict(list)

        # Load the attributes based on the template
        loaded_fields = []
        for dictionary in template:
            if not isinstance(dictionary, dict):
                raise AssertionError(
                    f'Positional argument "{dictionary}" passed must be a dict.'
                    f"This argument serves as a template for loading common "
                    f"values.",
                )
            for field_name, val in dictionary.items():
                loaded_fields.append(field_name)
                setattr(self, field_name, val)

        # Now load against the keyword arguments
        for field_name, val in kwargs.items():
            # Record that a field was encountered by appending to `loaded_fields`
            #   When it fails validations, we want it's errors to be recorded
            #
            #   Not remembering the field was recorded will result in it being set to `None`
            #   which will raise a ValidationError of its own for the wrong reasons (required field not set)
            loaded_fields.append(field_name)
            try:
                setattr(self, field_name, val)
            except ValidationError as err:
                for field_name in err.messages:
                    self.errors[field_name].extend(err.messages[field_name])

        # Now load the remaining fields with a None value, which will fail
        # for required fields
        for field_name in fields(self):
            if field_name not in loaded_fields:
                setattr(self, field_name, None)

        self.defaults()

        # `clean()` will return a `defaultdict(list)` if errors are to be raised
        custom_errors = self.clean() or {}
        for field in custom_errors:
            self.errors[field].extend(custom_errors[field])

        # Raise any errors found during load
        if self.errors:
            logger.error(self.errors)
            raise ValidationError(self.errors)

    def _run_validators(self, value):
        """Collect validators from enclosed fields and run them.

        This method is called during initialization of the Value Object
        at the Entity level.
        """
        errors = defaultdict(list)
        for field_name, field_obj in fields(self).items():
            try:
                field_obj._run_validators(getattr(self, field_name), value)
            except ValidationError as err:
                errors[field_name].extend(err.messages)

        if errors:
            raise ValidationError(errors)


def value_object_factory(element_cls, **kwargs):
    element_cls = derive_element_class(element_cls, BaseValueObject, **kwargs)

    return element_cls
