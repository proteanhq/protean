========
Entities
========

An Entity is a business object of the application, representing a chunk of domain data along with associated behavior. They could be simple data structures, but commonly incorporate domain behavior that operates on the data.

An Entity is usually distinguished by its identity, typically implemented as a primary key in a database. 

Entities are usually backed by a database and are persisted through a mapper.

.. Fat models

.. toctree::
   :maxdepth: 1

   definition
   field-types
   lifecycle
   querying
