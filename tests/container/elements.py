# Protean
from protean.core.exceptions import ValidationError, NotSupportedError
from protean.core.field.basic import String
from protean.utils.container import _ContainerMetaclass


class CustomBaseContainer(metaclass=_ContainerMetaclass):
    def __new__(cls, *args, **kwargs):
        if cls is CustomBaseContainer:
            raise TypeError("BaseDataTransferObject cannot be instantiated")
        return super().__new__(cls)

    def __init__(self, *template, owner=None, **kwargs):
        """
        Initialise the CustomContainer.

        During initialization, set value on fields if vaidation passes.

        This initialization technique supports keyword arguments as well as dictionaries. You
            can even use a template for initial data.
        """

        if self.meta_.abstract is True:
            raise NotSupportedError(
                f'{self.__class__.__name__} class has been marked abstract'
                f' and cannot be instantiated')

        self.errors = {}

        # Load the attributes based on the template
        loaded_fields = []
        for dictionary in template:
            if not isinstance(dictionary, dict):
                raise AssertionError(
                    f'Positional argument "{dictionary}" passed must be a dict.'
                    f'This argument serves as a template for loading common '
                    f'values.'
                )
            for field_name, val in dictionary.items():
                loaded_fields.append(field_name)
                setattr(self, field_name, val)

        # Now load against the keyword arguments
        for field_name, val in kwargs.items():
            loaded_fields.append(field_name)
            setattr(self, field_name, val)

        # Now load the remaining fields with a None value, which will fail
        # for required fields
        for field_name, field_obj in self.meta_.declared_fields.items():
            if field_name not in loaded_fields:
                setattr(self, field_name, None)

        # Raise any errors found during load
        if self.errors:
            raise ValidationError(self.errors)

        self.clean()

    def clean(self):
        """Placeholder method for validations.
        To be overridden in concrete Container classes, when complex
        validations spanning multiple fields are required.
        """


class CustomContainer(CustomBaseContainer):
    foo = String(max_length=50, required=True)
    bar = String(max_length=50, required=True)
