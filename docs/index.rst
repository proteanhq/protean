Protean
=======

Release v\ |version|

.. image:: https://github.com/proteanhq/protean/actions/workflows/ci.yml/badge.svg?branch=master
    :target: https://github.com/proteanhq/protean/actions
    :alt: Build Status
.. image:: https://codecov.io/gh/proteanhq/protean/branch/master/graph/badge.svg
    :target: https://codecov.io/gh/proteanhq/protean
    :alt: Coverage
.. image:: https://pyup.io/repos/github/proteanhq/protean/shield.svg
    :target: https://pyup.io/repos/github/proteanhq/protean/
    :alt: Updates

Protean is a DDD and CQRS-based framework that helps you build Event-driven applications.

Get started with :doc:`user/installation` and then get an overview with the :doc:`user/quickstart`.

.. warning:: Protean's documentation is *Work-In-Progress* - there are significant portions of
    functionality still missing. Refer to the contribution guide to help grow the documentation.

-------------------

Overview
--------

Protean helps you build applications that can scale and adapt to growing requirements without significant rework.

At its core, Protean encourages a Domain-Driven Design (DDD) approach to development, with support for artifacts
necessary to express your domain succinctly and precisely. It also allows you to remain agnostic to the underlying
technology by keeping implementation details out of view.

Protean can be thought of having three capabilities:

- *Service-Oriented*
  - Develop your application as one or more subdomains that run independently as Microservices
- *Event-Driven*:
  - Use events to propagate changes across subdomains or become eventually consistent within a Bounded Context.
- *Adapter-based*:
  - Use Remain technology-agnostic by exposing Port interfaces to the infrastructure, with multiple adapters
  supported out of the box.

Read :doc:`user/foreword` to understand Protean's philosophy.

.. note:: It is assumed that you have some prior knowledge about *Domain-Driven Design* (DDD) and *Command Query
    Responsibility Segregation* (CQRS) architectural patterns.

    If you do not have sufficient background in these topics, you should go through standard texts
    to understand Protean's behavior better.

.. warning:: **Protean** is currently under active development. APIs and interfaces are to be expected to change
    drastically and newer releases will almost certainly be backward incompatible.

    If you are interested in using Protean for your project, you may want to wait for the announcement of first
    stable production-ready version. If you want to use the framework *right now*, drop us an
    `email <subhash.bhushan@gmail.com>`_.

-------------------

User Guide
----------

.. toctree::
    :maxdepth: 2

    user/foreword
    user/installation
    user/quickstart
    user/composing-a-domain
    user/domain-definition
    user/entities-and-vos
    user/fields
    user/persistence
    user/services
    user/eventing
    user/config
    user/cli

Adapters
--------

.. toctree::
    :maxdepth: 1

    adapters/database

API Reference
-------------

If you are looking for information on a specific function, class or
method, this part of the documentation is for you.

.. toctree::
    :maxdepth: 2

    api

Community
---------

The best way to track the development of Protean is through the `the GitHub repo <https://github.com/proteanhq/protean>`_.

.. toctree::
    :maxdepth: 1

    community/changelog
    community/code-of-conduct
    community/contributing
