Definition
----------

An Entity represents a Domain Object. It contains one or more groups of attributes related to the domain object and generally maps to well-defined persisted structures in a database.

In short:

* Each entity is a Python class that subclasses ``protean.core.entity.Entity``.
* Each attribute of the entity represents a Data Attribute.
* An Entity can be persisted to a mapped repository during runtime, purely by configurations

Fields
^^^^^^

An Entity typically has one or more attributes associated with it, in the form of Fields. Such fields are typically specified as class attributes and their names cannot clash with published Entity API attributes like `clean`, `save`, or `delete`.


``Meta`` options
^^^^^^^^^^^^^^^^