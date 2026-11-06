
# Set up Protean

## Install Python

!!! note
    Protean supports Python 3.11 and newer. Use the latest version of Python.

[pyenv](https://github.com/pyenv/pyenv) allows you to install and manage
multiple versions of python. Follow pyenv's
[installation](https://github.com/pyenv/pyenv?tab=readme-ov-file#installation)
guide to install Python 3.11+.

Many version managers can create virtual environments. The steps below use
`venv`, which comes bundled with Python.

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

This installs a lean core: everything you need to define a domain, persist
through the in-memory adapter, and run the async engine (`protean server`).

## Install optional features

Protean ships some features as install extras so the core package stays small
(see the decision on the runtime dependency boundary and extras,
[ADR-0029](https://github.com/proteanhq/protean/blob/main/docs/adr/0029-runtime-dependency-boundary-and-extras.md)).
Install the extra for what you use:

| Extra | Install | Enables |
|-------|---------|---------|
| `server` | `pip install "protean[server]"` | the Observatory dashboard (`protean observatory`) and the FastAPI integration |
| `shell` | `pip install "protean[shell]"` | the interactive domain shell (`protean shell`) |
| `scaffold` | `pip install "protean[scaffold]"` | project scaffolding (`protean new`) |
| `cli` | `pip install "protean[cli]"` | the full interactive CLI (`shell` + `scaffold`) |
| `all` | `pip install "protean[all]"` | all of the above |

Adapters are extras too, for example `pip install "protean[postgresql]"` or
`pip install "protean[redis]"`. You can combine extras:
`pip install "protean[server,postgresql]"`.

If you run a command without its extra, Protean tells you which one to install
rather than failing with a raw import error.

## Verify the installation

Use the ``protean`` CLI to verify the installation:

```shell
$ protean --version
Protean 0.18.0
```

To verify that Protean can be seen by your current installation of Python,
try importing Protean from a ``python`` shell:

```shell
$ python
>>> import protean
>>> protean.get_version()
'0.18.0'
```

## Upgrading an existing project?

Start with the [migration guides](../../reference/migration/index.md). Each
release has one page that says what changed and what you need to do. Read every
guide between your current version and the one you are moving to.

Then let the framework tell you what your own code needs:

```shell
$ protean upgrade-check --domain=my_app
```

The upgrade check inspects your domain, and your live schema when it can reach
the database. It reports what needs attention, with the SQL to apply. It is
read-only: nothing is changed for you.

-------------------

That is all you need. The tutorial is a good next step.
