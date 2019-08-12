Protean
=======

*The Pragmatic Framework for Ambitious Applications*

Welcome to Protean's Documentation.

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

Get started with :ref:`install` and then get a overview with :ref:`quickstart`. There is also a more detailed :ref:`tutorial` that shows how to create a small but complete application with Protean. The rest of the docs describe each component of Protean in detail, with a full reference in the API section.

Overview
--------

**Protean** Framework helps you build ever-evolving applications that can scale and adapt to growing requirements without significant refactoring.

Protean at its core is a programming model that encourages domain driven design, with tools necessary to express your business logic succinctly and precisely while remaining agnostic to the underlying technology. It also provides operational tools to build and maintain a sophisticated infrastructure that allows you to scale and distribute robust, mission-critical applications, through cutting-edge DevOps utilities. Read the full philosophy in :ref:`foreword`.

Protean is a great fit for you if you are:

- Building robust, mission-critical applications for complex and uncharted domains
- Creating innovative products that will adapt and evolve over long cycles
- Porting complicated Legacy applications onto newer technology stacks

*Protean is free, open source, and always will be.*

.. warning:: **Protean** is currently under active development. APIs and Interfaces are to be expected to change drastically and newer releases will almost certainly be backward incompatible. If you are interested in using Protean for your project, you may want to wait for the announcement of first stable production-ready version. If you want to use the framework *right now*, drop us an `email <subhash.bhushan@gmail.com>`_.

Goals
-----

Protean has two broad goals in mind:

**1. Isolate Business logic from the underlying technology and closely model it after the Domain**

Developers should be able to express infrastructure-free domain logic in a clear and concise way, without worrying about underlying technology implementation. The framework should be pragmatic enough, though, and allow usage of exclusive technology features where possible for performance or aesthetics. Developers can delay critical decisions until the last possible moment and switch between technologies painlessly if and when the time does come.

**2. Support Operations and Infrastructure maintenance**

Developers should be able to deploy and scale applications in realtime on most popular IaaS platforms as well as private data centers. All infrastructure components, like databases, API frameworks, message brokers and cache, are maintained outside the application and plugged into the framework during runtime.

Key Features
------------

Protean is ready for today's diverse and multilayered software stack requirements:

- Lightweight APIs
- Non-opinionated and non-enforcing Application Code structure
- Abstract implementations for well-understood design patterns
- Expressive Domain Language for both developers as well as Business Users
- Full support for Domain-Driven Design
- Support for a variety of SQL and NoSQL Databases
- Ready to use plugins for popular API frameworks like Flask and Pyramid
- Extendable interfaces to build custom plugins
- Concrete Implementations for typical Business requirements like Authentication and Notifications
- Container support for Docker
- Kubernetes driven deployment mechanisms
- Out-of-the-box support for deploying into AWS, Azure and GCP

*Protean officially supports Python 3.7+.*

Guides
------

Protean guides contain a mixture of Architecture Principles, Conventions, Practical Considerations, Protean Opinions/Choices and Sample code. Wherever applicable, additional links to reference materials have been provided.

These guides have been heavily influenced by the thoughts and works of DDD pioneers. Specifically, it references extensively to the following texts:

* |ddd-eric-evans|
* |implementing-ddd-vaughn-vernon|
* |ddd-distilled-vaughn-vernon|

*Protean's guides are not a replacement to the original texts. It is recommended that you go through them to polish your DDD knowledge.*

.. toctree::
    :maxdepth: 1
    :caption: Philosophy

    philosophy/why-protean
    philosophy/decision-delay
    philosophy/architecture/dependency-rule

.. toctree::
   :maxdepth: 1
   :caption: User Guide

   user/foreword
   user/install
   user/quickstart
   user/tutorial
   user/composition-root
   user/domain-layer-mechanics
   user/application-layer-mechanics
   user/configuration
   user/infrastructure
   user/persistence
   user/unit-of-work
   user/messaging-medium
   user/negative-patterns

API
---

.. toctree::
   :maxdepth: 1
   :caption: API

   api/domain
   api/entity
   api/field
   api/queryset
   api/brokers
   api/utils
   api/in-memory-broker


Plugins
-------

.. toctree::
   :maxdepth: 1
   :caption: Plugins

   plugins/broker


.. toctree::
   :maxdepth: 1
   :caption: Community

   community/changelog
   community/styleguide
   Code of Conduct <community/code-of-conduct>
   community/contributing


.. |ddd-eric-evans| raw:: html

    <a href="https://www.amazon.com/Domain-Driven-Design-Tackling-Complexity-Software-ebook/dp/B00794TAUG" target="_blank">Domain-Driven Design: Tackling Complexity in the Heart of Software - Eric Evans</a>

.. |implementing-ddd-vaughn-vernon| raw:: html

    <a href="https://www.amazon.com/Implementing-Domain-Driven-Design-Vaughn-Vernon-ebook/dp/B00BCLEBN8" target="_blank">Implementing Domain-Driven Design - Vaughn Vernon</a>

.. |ddd-distilled-vaughn-vernon| raw:: html

    <a href="https://www.amazon.com/Domain-Driven-Design-Distilled-Vaughn-Vernon-ebook/dp/B01JJSGE5S" target="_blank">Domain-Driven Design Distilled - Vaughn Vernon</a>
