Installation
============

Python Version
--------------

We recommend using the latest version of Python. Protean supports Python 3.7+.

Virtual environments
--------------------

We highly recommend using virtual environments to manage the dependencies for your project.

A virtual environment allows you to install multiple Python versions side-by-side, without interfering with system-default Python installations. They also allow you to work with different groups of Python libraries, one for each project, thereby preventing packages installed in one project from affecting other projects.

Python comes bundled with the :mod:`venv` module to create virtual
environments.


.. _install-create-env:

Create an environment
~~~~~~~~~~~~~~~~~~~~~

Create a project folder and a :file:`venv` folder within:

.. tabs::

    .. group-tab:: macOS/Linux

        .. code-block:: text

            $ mkdir myproject
            $ cd myproject
            $ python3 -m venv venv

    .. group-tab:: Windows

        .. code-block:: text

            > mkdir myproject
            > cd myproject
            > py -3 -m venv venv


.. _install-activate-env:

Activate the environment
~~~~~~~~~~~~~~~~~~~~~~~~

Before you work on your project, activate the corresponding environment:

.. tabs::

    .. group-tab:: macOS/Linux

        .. code-block:: text

            $ . venv/bin/activate

    .. group-tab:: Windows

        .. code-block:: text

            > venv\Scripts\activate

Your shell prompt will change to show the name of the activated
environment.

You can also use |pyenv| to manage your virtual environments.


Install Protean
---------------

Within the activated environment, install Protean with the following command:

.. code-block:: shell

    $ pip install protean


.. |pyenv| raw:: html

    <a href="https://github.com/pyenv/pyenv" target="_blank">pyenv</a>
