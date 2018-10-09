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

.. |docs| image:: https://readthedocs.org/projects/protean/badge/?style=flat
    :target: https://readthedocs.org/projects/protean
    :alt: Documentation Status

.. |version| image:: https://img.shields.io/pypi/v/protean.svg
    :alt: PyPI Package latest release
    :target: https://pypi.org/project/protean/

.. |wheel| image:: https://img.shields.io/pypi/wheel/protean.svg
    :alt: PyPI Wheel
    :target: https://pypi.org/project/protean/

.. |supported-versions| image:: https://img.shields.io/pypi/pyversions/protean.svg
    :alt: Supported versions
    :target: https://pypi.org/project/protean/

.. |supported-implementations| image:: https://img.shields.io/pypi/implementation/protean.svg
    :alt: Supported implementations
    :target: https://pypi.org/project/protean/


.. end-badges

Protean Application Framework

* Free software: BSD 3-Clause License

Installation
============

::

    pip install protean

Documentation
=============

https://protean.readthedocs.io/en/latest/

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


.. image:: https://api.codacy.com/project/badge/Grade/9671c011ee7f4266bb6c97af95309a8a
   :alt: Codacy Badge
   :target: https://app.codacy.com/app/subhashb/protean?utm_source=github.com&utm_medium=referral&utm_content=proteanhq/protean&utm_campaign=Badge_Grade_Dashboard