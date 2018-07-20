========
Overview
========

.. start-badges

.. list-table::
    :stub-columns: 1

    * - docs
      - |docs|
    * - tests
      - |
        |
    * - package
      - | |version| |wheel| |supported-versions| |supported-implementations|
        | |commits-since|

.. |docs| image:: https://readthedocs.org/projects/protean/badge/?style=flat
    :target: https://readthedocs.org/projects/protean
    :alt: Documentation Status

.. |version| image:: https://img.shields.io/pypi/v/protean.svg
    :alt: PyPI Package latest release
    :target: https://pypi.python.org/pypi/protean

.. |commits-since| image:: https://img.shields.io/github/commits-since/proteanhq/protean/0.0.3..svg
    :alt: Commits since latest release
    :target: https://github.com/proteanhq/protean/compare/0.0.3....master

.. |wheel| image:: https://img.shields.io/pypi/wheel/protean.svg
    :alt: PyPI Wheel
    :target: https://pypi.python.org/pypi/protean

.. |supported-versions| image:: https://img.shields.io/pypi/pyversions/protean.svg
    :alt: Supported versions
    :target: https://pypi.python.org/pypi/protean

.. |supported-implementations| image:: https://img.shields.io/pypi/implementation/protean.svg
    :alt: Supported implementations
    :target: https://pypi.python.org/pypi/protean


.. end-badges

Protean Application Framework

* Free software: BSD 3-Clause License

Installation
============

::

    pip install protean

Documentation
=============

https://protean.readthedocs.io/

Development
===========

::

    pyenv virtualenv -p python3.6 3.6.5 protean-dev

To run the all tests run::

    tox

Note, to combine the coverage data from all the tox environments run:

.. list-table::
    :widths: 10 90
    :stub-columns: 1

    - - Windows
      - ::

            set PYTEST_ADDOPTS=--cov-append
            tox

    - - Other
      - ::

            PYTEST_ADDOPTS=--cov-append tox
