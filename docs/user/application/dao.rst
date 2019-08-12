.. _dao:

===================
Data Access Objects
===================

Data Access Objects, or DAOs, are

You don't have to deal with DAOs directly unless you are overriding the schema mapping to match the underlying data store. When you do override, you can define a custom DAO for the aggregate, and register it:

.. code-block:: python

    from protean.core.field.basic import Identifier

    @domain.dao
    class UserSchema:
        u_id = Identifier()
