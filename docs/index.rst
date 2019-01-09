Protean: Clean Architecture Multi-Purpose (CAMP) Framework
==========================================================

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

**Protean** is a Clean Architecture oriented, Multi-Purpose Development Framework. Protean has been built to be customized to your needs, whether you are building a simple web app or an entire backend ecosystem for your company's offering.

.. warning:: **Protean** is currently under active development. APIs and Interfaces are to be expected to change drastically and newer releases will almost certainly be backward incompatible. If you are interested in using Protean for your project, you may want to wait for the first stable production-ready version 0.1.0. If you want to use the framework *right now*, drop us an `email <subhash@team8solutions.com>`_.

Beloved Features
----------------

Protean is ready for today's diverse software stack requirements.

- Out-of-the-box database support for Elasticsearch and everything that is accessible through SQLAlchemy.
- Lightweight APIs
- Helper packages like Authentic that take care of end-to-end authentication

Protean officially supports Python 3.6+.


The User Guide
--------------

This part of the documentation introduces some background information about protean, then focuses on step-by-step instructions for getting the most out of Protean.

.. toctree::
   :maxdepth: 2
   :caption: User Guide

   user/intro
   user/install
   user/quickstart
   user/advanced
   user/services
   user/adapters
   user/implementations

The Philosophy
--------------

If you want to understand the thought process behind why Protean came into existence and why Protean is strucutured the way it is, this section is for you.

.. toctree::
    :maxdepth: 1
    :caption: Philosophy

    philosophy/core
    philosophy/dependency-rule
    philosophy/decision-delay
    philosophy/independence
    philosophy/testability
    philosophy/interfaces
    philosophy/data-transfer-objects

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
