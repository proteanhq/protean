
Changelog
=========

0.0.1 (2018-07-15)
------------------

* First release on PyPI.

0.0.2 (2018-07-19)
------------------

* Entity Base Class

0.0.3 (2018-07-20)
------------------

* Add `bleach` as a setup requirement
* Add GeoPoint and Decimal Data Types to Entities

0.0.4 (2018-07-20)
------------------

* Add UseCase Utility Classes
* Add Repository Abstract Classes

0.0.5 (2018-07-21)
------------------

* Add Context Class

0.0.6 (2018-12-14)
------------------

* Repository rewritten from the ground up
* First base version for overall Protean functionality

0.0.7 (2019-01-16)
------------------

* Rename `Repository` to `Adapter`
* Rename `Schema` to `Model`
* Enhance Entity class to perform CRUD methods instead of relying on a separate Repo Factory

0.0.8 (2019-02-27)
------------------

* Introduction of `find_by()` method for Entities
* Introduction of `save()` method for Entities
* Support for Query Operators (>, >=, <, <=)
* Support for Conjunction Operators (AND, OR) in queries
* Change Fields to be full-fledged Descriptors to control getting/setting values
* Introduction of Support for References and Associations (HasOne and HasMany)
* Remove Pylint from static code analysis and use Flake8
