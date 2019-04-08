.. _entity-field:

Field Reference
---------------

.. _entity-field-options:

Field options
~~~~~~~~~~~~~

You can supply the following optional arguments to all field types.

``identifier``
^^^^^^^^^^^^^^

If ``True``, this field is the identifier for the entity.

If you don’t specify ``identifier=True`` for any fields in your model, Django will automatically add an `Integer` field to hold the identifier value, so you don’t need to set ``identifier=True`` on any of your fields unless you want to override the default identifier behavior. For more information, see **Identity** section.

The identifier field is read-only. If you change the value of the identifier on an existing object and then save it, a new object will be created alongside the old one.

``default``
^^^^^^^^^^^

Value to set as the default for the field. If specified, this value will be used during entity loading if the field value is missing.

This can be a value or a callable object. The callable will be called every time a new object is created.

``required``
^^^^^^^^^^^^

If ``True``, the field is not allowed to be blank. Default is `False`.

``unique``
^^^^^^^^^^

If ``True``, values in this field must be unique amongst all entities.

``value``
^^^^^^^^^
The value to be set for the field, usually specified during initialization time.

``validators``
^^^^^^^^^^^^^^
Validation classes that will be invoked when saving a new value to the field. Most fields have default validators in place where appropriate. See validators associated with each field in **Field Types** section.

``choices``
^^^^^^^^^^^
An iterable of 2-tuples to use as choices for this field. If this is given, the value assignable to the field will be limited to the choices given.

A choices list looks like this:

.. code-block:: python

    class Beverage(Entity):
        NON_ALCOHOLIC_DRINKS = (
            ('tea', 'Tea'),
            ('coffee', 'Coffee'),
            ('milk', 'Milk'),
            ('soda', 'Soda'),
        )
        name = field.String(max_length=50)
        non_alcoholic = field.String(choices=NON_ALCOHOLIC_DRINKS)

.. _entity-field-auto-identity:

Automatic Identity Field
~~~~~~~~~~~~~~~~~~~~~~~~

By default, Protean associates an ``id`` field with each entity:

.. code-block:: python

    id = field.Auto()

The value of this field is auto-generated if not specified manually. 

If you would like to specify a custom identifier, just specify ``identifier=True`` on one of your fields. If Protean sees an explicitly set ``Field.identifier``, it won't add the automatic ``id`` attribute.

.. code-block:: python

    account_id = field.Integer(identifier=True)

The identity field can be introspected later from the Entity through the ``id_field`` attribute in the Entity meta attributes.

An identity attribute, whether generated automatically or set explicitly, is always marked ``required=True`` and ``unique=True``.

.. _entity-field-types:

Field types
~~~~~~~~~~~

Each field in your entity should be an instance of the appropriate Field class. Protean uses the field class type to determine what kind of data can be stored (e.g. Integers, Strings, Boolean).

Protean is packaged with many built-in field types; you can find the complete list in the **Fields Types** section. You can also easily write your own fields when none of the existing types fit your need; see **Writing custom fields** section.


.. _entity-field-auto:

Auto
^^^^

.. class:: Auto(*args, **kwargs)

A field that holds automatically incrementing values. The ID value itself could be an integer (like in the case of most RDBMSs) or a string (like in the case of NoSQL databases), or a string in a specific format (like in the case of UUID/GUID). You usually won't need to access this field directly. If you don't specify an ``Auto`` field explicitly, a primary key field will automatically be added to your entity. See :ref:`entity-field-auto-identity`.

.. _entity-field-date:

Date
^^^^

.. class:: Date(*args, **kwargs)

A date represented in Python by a datetime.date instance.

.. _entity-field-datetime:

DateTime
^^^^^^^^

.. class:: DateTime(*args, **kwargs)

A date and time represented in Python by a datetime.datetime instance.

.. _entity-field-float:

Float
^^^^^

.. class:: Float(*args, **kwargs)

A floating-point number represented in Python by a float instance.

.. _entity-field-integer:

Integer
^^^^^^^

.. class:: Integer(*args, **kwargs)

An integer. Values typically range from-2147483648 to 2147483647.

.. _entity-field-boolean:

Boolean
^^^^^^^

.. class:: Boolean(*args, **kwargs)

A true/false field.

.. _entity-field-string:

String
^^^^^^

.. class:: String(*args, **kwargs)

A string field, for small- to large-sized strings.

For large amounts of text, use Text.

.. _entity-field-text:

Text
^^^^

.. class:: Text(*args, **kwargs)

A large text field.

.. _entity-field-list:

List
^^^^

.. class:: List(*args, **kwargs)

A special field capable of holding List values of one single type.

.. _entity-field-dict:

Dict
^^^^

.. class:: Dict(*args, **kwargs)

A special field capable of holding a dictionary of key-values.

.. _entity-field-custom:

Writing custom fields
~~~~~~~~~~~~~~~~~~~~~

.. // TODO Add Custom Field Documentation

<TO BE DOCUMENTED>