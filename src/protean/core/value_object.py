"""Value Object Functionality and Classes"""

import inspect
import logging
from collections import defaultdict

from protean.exceptions import IncorrectUsageError, NotSupportedError, ValidationError
from protean.fields import Reference, ValueObject
from protean.fields.association import Association
from protean.utils import DomainObjects, derive_element_class
from protean.utils.container import BaseContainer, OptionsMixin, fields

logger = logging.getLogger(__name__)


class BaseValueObject(BaseContainer, OptionsMixin):
    element_type = DomainObjects.VALUE_OBJECT

    def __new__(cls, *args, **kwargs):
        if cls is BaseValueObject:
            raise NotSupportedError("BaseValueObject cannot be instantiated")
        return super().__new__(cls)

    @classmethod
    def _default_options(cls):
        return [
            ("abstract", False),
            ("part_of", None),
        ]

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()

        # Record invariant methods
        setattr(cls, "_invariants", defaultdict(dict))

        cls.__validate_for_basic_field_types()
        cls.__validate_for_non_identifier_fields()
        cls.__validate_for_non_unique_fields()

    @classmethod
    def __validate_for_basic_field_types(cls):
        for field_name, field_obj in fields(cls).items():
            # Value objects can hold all kinds of fields, except associations
            if isinstance(field_obj, (Reference, Association)):
                raise IncorrectUsageError(
                    f"Value Objects cannot have associations. "
                    f"Remove {field_name} ({field_obj.__class__.__name__}) from class {cls.__name__}"
                )

    @classmethod
    def __validate_for_non_identifier_fields(cls):
        for field_name, field_obj in fields(cls).items():
            if field_obj.identifier:
                raise IncorrectUsageError(
                    f"Value Objects cannot contain fields marked 'identifier' (field '{field_name}')"
                )

    @classmethod
    def __validate_for_non_unique_fields(cls):
        for field_name, field_obj in fields(cls).items():
            if field_obj.unique:
                raise IncorrectUsageError(
                    f"Value Objects cannot contain fields marked 'unique' (field '{field_name}')"
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

        # Set the flag to prevent any further modifications
        self._initialized = False

        # Load the attributes based on the template
        loaded_fields = []
        for dictionary in template:
            if not isinstance(dictionary, dict):
                raise AssertionError(
                    f"Positional argument {dictionary} passed must be a dict. "
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

        # Load Value Objects from associated fields
        #   This block will dynamically construct value objects from field values
        #   and associated the vo with the entity
        # If the value object was already provided, it will not be overridden.
        for field_name, field_obj in fields(self).items():
            if isinstance(field_obj, (ValueObject)) and not getattr(self, field_name):
                attrs = [
                    (embedded_field.field_name, embedded_field.attribute_name)
                    for embedded_field in field_obj.embedded_fields.values()
                ]
                values = {name: kwargs.get(attr) for name, attr in attrs}
                try:
                    value_object = field_obj.value_object_cls(**values)
                    # Set VO value only if the value object is not None/Empty
                    if value_object:
                        setattr(self, field_name, value_object)
                        loaded_fields.append(field_name)
                except ValidationError as err:
                    for sub_field_name in err.messages:
                        self.errors["{}_{}".format(field_name, sub_field_name)].extend(
                            err.messages[sub_field_name]
                        )

        # Now load the remaining fields with a None value, which will fail
        # for required fields
        for field_name in fields(self):
            if field_name not in loaded_fields:
                setattr(self, field_name, None)

        self.defaults()

        # `_postcheck()` will return a `defaultdict(list)` if errors are to be raised
        custom_errors = self._postcheck() or {}
        for field in custom_errors:
            self.errors[field].extend(custom_errors[field])

        # If we made it this far, the Value Object is initialized
        #   and should be marked as such
        self._initialized = True

        # Raise any errors found during load
        if self.errors:
            logger.error(self.errors)
            raise ValidationError(self.errors)

    def __setattr__(self, name, value):
        if not hasattr(self, "_initialized") or not self._initialized:
            return super().__setattr__(name, value)
        else:
            raise IncorrectUsageError(
                "Value Objects are immutable and cannot be modified once created"
            )

    def _postcheck(self, return_errors=False):
        """Invariant checks performed after initialization"""
        errors = defaultdict(list)

        for invariant_method in self._invariants["post"].values():
            try:
                invariant_method(self)
            except ValidationError as err:
                for field_name in err.messages:
                    errors[field_name].extend(err.messages[field_name])

        if return_errors:
            return errors

        if errors:
            raise ValidationError(errors)


def value_object_factory(element_cls, domain, **opts):
    element_cls = derive_element_class(element_cls, BaseValueObject, **opts)

    # Iterate through methods marked as `@invariant` and record them for later use
    methods = inspect.getmembers(element_cls, predicate=inspect.isroutine)
    for method_name, method in methods:
        if not (
            method_name.startswith("__") and method_name.endswith("__")
        ) and hasattr(method, "_invariant"):
            element_cls._invariants[method._invariant][method_name] = method

    return element_cls
