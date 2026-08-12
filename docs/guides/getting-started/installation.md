
# Installation

## Install Python

!!! note
    Protean supports Python 3.11 and newer, but it is recommended that you
    use the latest version of Python.

[pyenv](https://github.com/pyenv/pyenv) allows you to install and manage
multiple versions of python. Follow pyenv's
[installation](https://github.com/pyenv/pyenv?tab=readme-ov-file#installation)
guide to install Python 3.11+.

There are many version managers that help you create virtual environments,
but we will quickly walk through the steps to create a virtual environment with
one bundled with Python, `venv`.

## Create a virtual environment

Create a project folder and a `.venv` folder within. Follow Python's
[venv guide](https://docs.python.org/3/library/venv.html) to install a new
virtual environment.

```shell
$ python3 -m venv .venv
```

## Activate the environment

```shell
$ source .venv/bin/activate
```

Your shell prompt will change to show the name of the activated environment.

You can verify the Python version by typing ``python`` from your shell;
you should see something like
```shell
$ python --version
Python 3.11.8
```

## Install Protean

Within the activated environment, install Protean with the following command:

```shell
$ pip install protean
```

## Verifying

Use the ``protean`` CLI to verify the installation:

```shell
$ protean --version
Protean 0.17.1
```

To verify that Protean can be seen by your current installation of Python,
try importing Protean from a ``python`` shell:

```shell
$ python
>>> import protean
>>> protean.get_version()
'0.17.1'
```

## Upgrading an existing project?

Start with the [migration guides](../../reference/migration/index.md), which
carry one page per release describing what changed and what to do about it.
Read every guide between your current version and the one you are moving to.

Then let the framework tell you what your own code needs:

```shell
$ protean upgrade-check --domain=my_app
```

It inspects your domain and, where it can reach the database, your live schema,
and reports what needs attention with the SQL to apply. It is read-only: nothing
is changed for you.

-------------------

That's it! You can now get a sneak peek into Protean with a quick tutorial.
