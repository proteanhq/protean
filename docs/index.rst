Protean
=======

*The Pragmatic Framework for Ever-evolving Applications*

Release v\ |version|. (:ref:`Changelog <changelog>`)

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

.. image:: https://codecov.io/gh/proteanhq/protean/branch/master/graph/badge.svg
    :target: https://codecov.io/gh/proteanhq/protean

**Protean** is a Python Framework that encourages domain driven design, providing the tools necessary to express your business logic succinctly and precisely while remaining agnostic to underlying technology.

It is a great fit for you if you are:

- Building robust, mission-critical applications for complex and uncharted domains
- Porting complicated Legacy applications onto newer technology stacks
- Creating innovative products that will adapt and evolve over long cycles

*Protean is free, open source, and always will be.*

.. warning:: **Protean** is currently under active development. APIs and Interfaces are to be expected to change drastically and newer releases will almost certainly be backward incompatible. If you are interested in using Protean for your project, you may want to wait for the first stable production-ready version 0.1.0. If you want to use the framework *right now*, drop us an `email <subhash.bhushan@gmail.com>`_.

Goals
-----

Protean has two broad goals in mind:

**1. Isolated Business logic closely modeled after the Domain**

Developers should be able to express infrastructure-free domain logic in a clear and concise way, without worrying about underlying technology implementation. The framework should be pragmatic enough, though, and allow incorporatoin of special technology features for performance or aesthetics.

**2. Technology-agnostic and Framework independent applications**

Developers should be able to develop applications detached from the underlying infrastructure, like databases, API frameworks, message brokers and so on.

Developers can then delay critical decisions until the last possible moment. Also, If and when the time comes, it enables them to switch between technologies painlessly.

Key Features
------------

Protean is ready for today's diverse and layered software stack requirements:

- Lightweight APIs
- Non-opinionated and non-enforcing Application Code organization
- Abstract implementations for well-understood design patterns
- Expressive Domain Language for both developers as well as Business Users
- Full support for Domain-Driven Design
- Out-of-the-box database support for SQL and NoSQL Databases
- Ready to use plugins for popular API frameworks like Flask and Pyramid
- Extendable interfaces to build your own plugins
- Concrete Implementations for typical Business requirements like Authentication and Notifications

Protean officially supports Python 3.6+.

.. toctree::
    :maxdepth: 1
    :caption: Philosophy

    philosophy/why-protean
    philosophy/decision-delay
    philosophy/architecture/dependency-rule


.. toctree::
   :maxdepth: 1
   :caption: Introduction

   intro/install


.. toctree::
   :maxdepth: 1
   :caption: User Guide

   user/entities/index

.. toctree::
   :maxdepth: 1
   :caption: API

   api/entity
   api/queryset

.. toctree::
   :maxdepth: 1
   :caption: Community

   community/changelog
   Code of Conduct <community/code-of-conduct>
   community/contributing