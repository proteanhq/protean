.. _api-field:

=====
Field
=====

.. _api-field-value:

``value``
---------

Returns the value stored in the field object.

.. _api-field-validators:

``validators``
--------------

Returns a list of validators associated with the field.


Basic Fields
------------

// FIXME Attach caption to reference

``Auto``
^^^^^^^^

.. _api-field-basic-auto:

`Auto` fields serve as placeholders of unique identity values that are auto-generated. Refer to :ref:`identity` for detailed information about different identity options and configuring them for your domain.


``Identifier``
^^^^^^^^^^^^^^

.. _api-field-basic-identifier:

`Identifier` fields serve as placeholders of identity values. The values can be either *Unique Identifiers* of Aggregates/Entities/Views, or referential keys for other domain elements (Foreign Keys).
