
Release History
===============

0.0.10 (2019-04-05)
-------------------

* Support for chained `update` and `delete` methods on Queryset
* Support for `update_all` method for mass updates on objects
* Support for `delete_all` method for mass deletion of objects
* Rename databases configuration key in Config file from ``REPOSITORIES`` to ``DATABASES``
* Fully expand the Provider class in configuration file, to avoid assuming a Provider class name
* Split ``Adapter`` class into ``Provider`` and ``Repository``, separating the concern of managing the database connection from performing CRUD operations on Entity data
* Expose configured databases as ``providers`` global variable
* Allow fetching new connection on demand of a new repository object via ``get_connection`` in ``providers``
* Rename ``Lookup`` class to ``BaseLookup``
* Associate Lookups with Concrete Provider classes
* Provide option to fully bake a model class in case it needs to be decorated for a specific database, via the ``get_model`` method in concrete Provider class
* Add support for Entity Namespacing
* Refactor Repository Factory for better consistency of registry

0.0.9 (2019-03-08)
------------------

* Minor fixes for issues found while migrating SQLAlchemy plugin to 0.0.8 version
* `delete` method should query by value of `id_field` instead of hardcoded `id`

0.0.8 (2019-02-27)
------------------

* Introduction of `find_by()` method for Entities
* Introduction of `save()` method for Entities
* Support for Query Operators (>, >=, <, <=)
* Support for Conjunction Operators (AND, OR) in queries
* Change Fields to be full-fledged Descriptors to control getting/setting values
* Introduction of Support for References and Associations (HasOne and HasMany)
* Remove Pylint from static code analysis and use Flake8

0.0.7 (2019-01-16)
------------------

* Rename `Repository` to `Adapter`
* Rename `Schema` to `Model`
* Enhance Entity class to perform CRUD methods instead of relying on a separate Repo Factory

0.0.6 (2018-12-14)
------------------

* Repository rewritten from the ground up
* First base version for overall Protean functionality

0.0.5 (2018-07-21)
------------------

* Add Context Class

0.0.4 (2018-07-20)
------------------

* Add UseCase Utility Classes
* Add Repository Abstract Classes

0.0.3 (2018-07-20)
------------------

* Add `bleach` as a setup requirement
* Add GeoPoint and Decimal Data Types to Entities

0.0.2 (2018-07-19)
------------------

* Entity Base Class

0.0.1 (2018-07-15)
------------------

* First release on PyPI.
