Defining Entities
-----------------

An Entity is a meaningful Domain Object. It contains one or more groups of attributes related to the concept and generally maps to well-defined persisted structures.

The basics:

* Each entity is a Python class that subclasses ``protean.core.entity.Entity``.
* Each attribute of the entity represents a Data Attribute.
* An Entity can be persisted to a mapped repository during runtime, purely by configurations

Fields
^^^^^^

An Entity typically has one or more attributes associated with it, in the form of Fields. Such fields are typically specified as class attributes and their names cannot clash with published Entity API attributes like `clean`, `save`, or `delete`.

Field types
~~~~~~~~~~~

Each field in your entity should be an instance of the appropriate Field class. Protean uses the field class type to determine what kind of data can be stored (e.g. Integers, Strings, Boolean).

Protean is packaged with many built-in field types; you can find the complete list in the **Fields Types** section. You can also easily write your own fields when none of the existing types fit your need; see **Writing custom fields** section.

Field options
~~~~~~~~~~~~~

``identifier``

If True, this field is the identifier for the entity.

If you don’t specify ``identifier=True`` for any fields in your model, Django will automatically add an `Integer` field to hold the identifier value, so you don’t need to set ``identifier=True`` on any of your fields unless you want to override the default identifier behavior. For more information, see **Identity** section.

The identifier field is read-only. If you change the value of the identifier on an existing object and then save it, a new object will be created alongside the old one.

``default``

The default value for the field. If set, this value will be used during entity loading if the field value is missing.

This can be a value or a callable object. If callable it will be called every time a new object is created.

``required``

If `True`, the field is not allowed to be blank. Default is `False`.

``unique``

If `True`, values in this field must be unique amongst all entities.

``value``
The value to be set for the field, usually specified during initialization time.

``validators``
Validation classes that will be invoked when saving a new value to the field. Most fields have default validators in place where appropriate. See validators associated with each field in **Field Types** section.

``choices``
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

Automatic Identity Field
^^^^^^^^^^^^^^^^^^^^^^^^

By default, Protean associates an ``id`` field with each entity:

.. code-block:: python

    id = field.Auto()

The value of this field is auto-generated if not specified manually. 

If you would like to specify a custom identifier, just specify ``identifier=True`` on one of your fields. If Protean sees an explicitly set ``Field.identifier``, it won't add the automatic ``id`` attribute.

.. code-block:: python

    account_id = field.Integer(identifier=True)

The identity field can be introspected later from the Entity through the ``id_field`` attribute in the Entity meta attributes.

An identity attribute, whether generated automatically or set explicitly, is always marked ``required=True`` and ``unique=True``.
