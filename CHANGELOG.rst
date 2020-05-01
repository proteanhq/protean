Release History
===============

0.5.0 (2020-05-01)
------------------

* Bugfix #304 - Remove shadow object linkages with aggregates
* Raise InvalidDataError on invalid attributes to Commands
* Treat meta attributes like auto_fields and mandatory_fields as dicts instead of tuples
* Add support for nested serializers/schemas with Marshmallow
* Bugfix to not link shadow fields with Aggregate/Entity classes directly
* Bugfix to set initialize Shadow (Reference) and Value Object attributes correctly
* Store Reference and Value Object fields in `Entity.meta_` for later use
* Allow Subscribers and Handlers to hook into multiple Domain Events
* Bugfix to avoid fetching child records without foreign key linkages
* Add support for Dict serialization
* Allow persisting and management of child entities via the Aggregate object
* Add support for using Celery as the background worker

0.4.0 (2020-03-16)
------------------

* Add support for referencing embedded fields with a defined name
* Fix to allow `default=False` on Boolean fields and subsequent filtering for `False` in field values
* Fix to use Entity attributes to derive field names of unique fields, instead of `declared_fields`
* Add support for logging events into a universal `EventLog` table before publishing to brokers
* Add support for custom models associated with Aggregates/Entities
* Use Elasticsearch specific List and Dict attributes to reconstruct entity
* Bugfix - Verify that ValueField object is not empty before trying to access its attributes
* Bugfix - Fix how Elasticsearch connection is fetched while resetting data

0.3.3 (2020-01-10)
------------------

* Email Notifications Functionality
* Support for SendGrid
* Allow ad-hoc Identity Generation

0.3.2 (2019-10-17)
------------------

* Auto-traversal bug fixes

0.3.1 (2019-10-15)
------------------

* Auto Traverse Domain Modules and load elements

0.3 (2019-10-09)
----------------

* Add a `defaults` method as part of Container objects when assigned defaults in one field based on another
* Add support for Command Handlers
* Avoid raising `ValidationError` when loading data from data stores
* Add support for Elasticsearch as a repository
* Add support for using Redis as a broker with RQ background workers

0.2 ((2019-09-16)
-----------------

* New Request Object elements introduced to package information from API/views
* A base Container class introduced for all Protean data objects for uniformity in behavior
* Support for specifying Data Type of auto-generated Identities (String, Integer or UUID)
* Enhancements and fixes for Unit of Work functionality to work well with SQLAlchemy type database plugins
* Unit of Work transactions now control event publishing and release events to the stream only on a successful commit
* A Simplified element registration process to the domain
* Validation bug fixes in Aggregates, Entities and Value Objects
* Fully functional and configurable logs throughout Protean codebase
* Test case restructuring for clarity and isolation of configurations

0.1 (2019-07-25)
----------------

* Full revamp of Protean codebase to adhere to DDD principles
* Add `Domain` Composition root, with support for the definition of multiple domains in a project
* Support for Domain Layer elements: Aggregates, Entities, Value Objects, Domain Services, and Domain Events
* Support for Application Layer elements: Application Services, Data Transfer Objects, Repositories, Subscribers and Serializers
* Support annotations to register elements with Domain
* Complete revamping of Repository layer, and introduction of an underlying DAO layer
* Add Unit of Work capabilities to support ACID transactions
* Collapse SQLAlchemy and Flask implementations in Protean itself temporarily, until API stabilizes
* Rename `success` flag on Response to `is_successful`
* Rename `message` attribute in Response object to `errors` with a uniform structure in all error cases

0.0.11 (2019-04-23)
-------------------

* Rename Repository abstract methods to be public (Ex. `_create_object` → `create`)
* Add `delete_all()` method to Entity to support Repository cleanup
* Add support for `raw` queries on Entity repositories
* Remove requirement for explicit Model definitions for Entities
* Move Model options into Entity `Meta` class
* Support for `pre_save` and `post_save` entity callbacks
* Replace `Pagination` with `ResultSet` because it is at Entity and Use Case level
* Replace `page` and `per_page` with `limit` and `offset`
* Add Command utility to generate Protean project template
* Provide command line utilities for `--version` and `test`
* Bug fix: Handled quotes and escape properly in string values in Dictionary repository
* Add documentation for Overriding Entity Life cycle methods
* Add ability to mark tests as slow and run slow tests in travis

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
* Add support for Entity Namespaces
* Refactor Repository Factory for better consistency of registry

0.0.9 (2019-03-08)
------------------

* Minor fixes for issues found while migrating SQLAlchemy plugin to 0.0.8 version
* `delete` method should query by value of `id_field` instead of hard-coded `id`

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
