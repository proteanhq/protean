Installation
============

Install Python
--------------

.. note:: Protean supports Python 3.7 and newer, but it is recommended that that you use the latest version of Python.

Virtual environments allow you to install multiple Python versions side-by-side, without interfering with system-default Python installations. They also help you to work with different groups of Python libraries, one for each project, thereby preventing packages installed in one project from affecting other projects.

There are many version managers that help you create virtual environments, like |pyenv| and |pipenv|, but we will quickly walk through the steps to create a virtual environment with one bundled with Python, :mod:`venv`.

.. |pyenv| raw:: html

    <a href="https://github.com/pyenv/pyenv" target="_blank">pyenv</a>

.. |pipenv| raw:: html

    <a href="https://github.com/pypa/pipenv" target="_blank">pipenv</a>


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

You can verify the Pyton version by typing ``python`` from your shell;
you should see something like::

    Python 3.8.10 (default, Jun 21 2021, 15:30:31)
    [Clang 12.0.5 (clang-1205.0.22.9)] on darwin
    Type "help", "copyright", "credits" or "license" for more information.
    >>>


Install Protean
---------------

Within the activated environment, install Protean with the following command:

.. code-block:: shell

    $ pip install protean


Verifying
---------

Use the ``protean`` command-line utility to verify the installation:

.. code-block:: shell

    $ protean --version
    0.11.0

To verify that Protean can be seen by Python, try importing Proteam from a ``python`` shell:

.. code-block:: shell

    $ python3
    >>> import protean
    >>> print(protean.get_version())
    0.11.0

-------------------

That's it! You can now move onto the :doc:`quickstart`.
