""" Module defines reusable Generic meta classes """

from abc import ABCMeta


class OptionsMeta(ABCMeta):
    """
    Generic metaclass that sets the ``opts`` class attribute, which is
    the Base class's ``class Meta`` options using the ``options_class`` attr .
    """

    def __new__(mcs, name, bases, attrs):
        klass = super().__new__(mcs, name, bases, attrs)

        # Get the Meta class attribute defined for the base class
        meta = getattr(klass, 'Meta', None)

        # Load the meta class attributes for non base schemas
        is_base = getattr(meta, 'base', False)
        if not is_base:
            # Set klass.opts by initializing the `OPTIONS_CLASS` with the meta
            klass.opts = klass.options_class(meta, klass)

        return klass
