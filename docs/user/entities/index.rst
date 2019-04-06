========
Entities
========

An Entity is a business object of the application, representing a chunk of domain data along with associated behavior. They could be simple data structures, but usually incorporate domain behavior that operates on the data.

The Concept
-----------

An Entity is not fundamentally defined by their attributes, but rather by a thread of continuity and identity. Such identities are typically implemented as primary keys in a database. The key value could be automatically generated or manually assigned. It could be a unique running sequence for the Entity type, or it could be a universally unique identifier (like a UUID.)

The entities are persisted, queried, compared, and destroyed by their identity alone. Even when an entity must be matched with another entity even though attributes differ, they are distinguished from each other even through their identity though they might have the same attributes. In other words, two entities are considered equal if and only if their identities match.

Their class definitions, responsibilities, attributes, and associations should revolve around who they are, rather than the particular attributes they carry. One could find entities by their data attribute values, but the lifecycle functions like `save`, `update` and `delete` are executed by identity value alone.

Objects that do not need to be persisted (typically those that do not have a thread of identity running through their lifecycle) are called Value Objects. Such objects do not have an identity associated with them and are constructed on the fly from data attributes.

Entities are usually backed by a database and are persisted through a mapper. Protean plugins allow a seamless transition between application code and database mapping, there by eliminating infrastructure details at the design stage but shortening the path to taking the application to production.

Quick Example
-------------

.. code-block:: python

    from protean.core.entity import Entity

    class Account(Entity):
        username = field.String(required=True, unique=True, max_length=50)
        email = field.String(required=True)
        password = field.StringLong(required=True, min_length=6)

`username`, `email` and `password` are attributes of the `Account` entity. Each field is specified as a class attribute, and each attribute maps to a corresponding field in the database.

Defining Entities
-----------------

.. toctree::
   :maxdepth: 1

   definition
   field-reference
   associations

Entity lifecycle
----------------

.. toctree::
   :maxdepth: 1

   lifecycle

Querying
--------

.. toctree::
   :maxdepth: 1

   querying
   field-lookups
   q-objects
   caching