Protean
=======

*The Pragmatic Framework for Ever-evolving Applications*

Release v\ |version|. (:ref:`Installation <install>`)

.. image:: https://readthedocs.org/projects/protean/badge/?style=flat
    :target: https://readthedocs.org/projects/protean

.. image:: https://img.shields.io/pypi/l/protean.svg
    :target: https://pypi.org/project/protean/

.. image:: https://img.shields.io/pypi/v/protean.svg
    :target: https://pypi.org/project/protean/

.. image:: https://img.shields.io/pypi/wheel/protean.svg
    :target: https://pypi.org/project/protean/

.. image:: https://img.shields.io/pypi/pyversions/protean.svg
    :target: https://pypi.org/project/protean/

.. image:: https://img.shields.io/pypi/implementation/protean.svg
    :target: https://pypi.org/project/protean/

.. image:: https://codecov.io/gh/proteanhq/protean/branch/master/graph/badge.svg
    :target: https://codecov.io/gh/proteanhq/protean

**Protean** is a Python Framework that encourages domain driven design, providing the tools necessary to express your business logic succinctly and precisely while remaining agnostic to underlying technology.

It is a great fit for you if you are:

- Building robust, mission-critical applications for complex domains
- Porting complicated Legacy applications onto newer technology stacks
- Creating products to adapt and evolve over long cycles

*Protean is free, open source, and always will be.*

.. warning:: **Protean** is currently under active development. APIs and Interfaces are to be expected to change drastically and newer releases will almost certainly be backward incompatible. If you are interested in using Protean for your project, you may want to wait for the first stable production-ready version 0.1.0. If you want to use the framework *right now*, drop us an `email <subhash@team8solutions.com>`_.

Beloved Features
----------------

Protean is ready for today's diverse software stack requirements.

- Out-of-the-box database support for Elasticsearch and everything that is accessible through SQLAlchemy.
- Lightweight APIs
- Helper packages like Authentic that take care of end-to-end authentication

Protean officially supports Python 3.6+.

Why we built Protean
--------------------

This reason why we built Protean and the thought-process behind its choices is explained here.

.. toctree::
    :maxdepth: 1
    :caption: Philosophy

    philosophy/why-protean
    philosophy/decision-delay
    philosophy/architecture/dependency-rule

The User Guide
--------------

This part of the documentation introduces some background information about protean, then focuses on step-by-step instructions for getting the most out of Protean.

.. note:: Protean's test code is littered with usage of a certain `Dog` class. If you find that discomforting, replace `Dog` with `CuteLittlePuppyDog` everywhere.

    **Disclosure**: No real dog was harmed in the process of building this framework.

.. toctree::
   :maxdepth: 2
   :caption: User Guide

   user/intro
   user/install
   user/quickstart
   user/entities
   user/data-transfer-objects
   user/advanced
   user/testing
   user/services
   user/adapters
   user/implementations

The Community Guide
-------------------

This part of the documentation details the Protean ecosystem and community.

.. toctree::
   :maxdepth: 2
   :caption: Community Guide

   community/adapters
   community/support
   community/changelog

API
---

If you are looking for information on a specific function, class, or method, this part of the documentation is for you.

.. toctree::
   :maxdepth: 2
   :caption: API

   api


The Contributor Guide
---------------------

If you want to contribute to the project, this part of the documentation is for you.

.. toctree::
   :maxdepth: 2
   :caption: Contributor Guide

   dev/philosophy
   dev/contributing
   dev/authors
