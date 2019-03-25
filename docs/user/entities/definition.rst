Defining Entities
-----------------

An Entity is a meaningful Domain Object. It contains one or more groups of attributes related to the concept and generally maps to well-defined persisted structures.

The basics:

* Each entity is a Python class that subclasses ``protean.core.entity.Entity``.
* Each attribute of the entity represents a Data Attribute.
* An Entity can be persisted to a mapped repository during runtime, purely by configurations

Fields
^^^^^^

A full listing of all supported types can be found in the **Fields Types** section.

Identity
^^^^^^^^

By default, Protean associates an `id` field with each entity:

.. code-block:: python

    id = field.Auto()

The value of this field is auto-generated if not specified manually. 

If you would like to specify a custom identifier, just specify `identifier=True` on one of your fields. If Protean sees an explicitly set `Field.identifier`, it won't add the automatic `id` attribute.

.. code-block:: python

    account_id = field.Integer(identifier=True)

The identity field can be introspected later from the Entity through the `id_field` attribute in the Entity meta attributes.

An identity attribute, whether generated automatically or set explicitly, is always marked `required` and `unique`.
