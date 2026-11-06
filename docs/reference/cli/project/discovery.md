# Domain Discovery

In most cases, you will use the `protean` script to interact with your domain
over the CLI. The script must be told where to find your domain to load and
initialize it, prepping it for your use. The `--domain` option is used to
specify how to load the domain.

While `--domain` supports a variety of options for specifying your domain,
the below typical values cover most use cases:

**(nothing)**

The command looks for the domain in this order:

1. A `domain` package or `domain.py` in the current directory.
2. A `subdomain` package or `subdomain.py` in the current directory.
3. `src/*/domain.py`, the layout that `protean new` creates.
4. `src/*/subdomain.py`.

A folder counts as a package only when it has an `__init__.py`.

When it finds a file under `src/` in a package folder that has an
`__init__.py`, as `protean new` creates it, the command adds `src` to the
import path and imports the file under its package name, such as
`demo.domain`. A `domain.py` under `src/` wins over a `subdomain.py` under
`src/`. When more than one `src/*/domain.py` matches, or more than one
`src/*/subdomain.py` matches and there is no `src/*/domain.py`, the command
stops with an error that lists every match. Pass `--domain` to choose one.
`--domain .` uses the same order.

**`--domain auth`**

The given name is imported, automatically detecting a domain (``domain`` or
``subdomain``).

!!! note

    ``--domain`` has three parts: an optional folder, a Python file or dotted
    import path, and an optional variable name of the instance. The command
    adds the folder to the import path. The following values demonstrate these
    parts:

    - ``--domain src/auth``
        Adds ``src`` to the import path and imports ``auth``.

    - ``--domain auth.domain``
        Adds the current directory to the import path and imports
        ``auth.domain``.

    - ``--domain auth:sso``
        Uses the ``sso`` Protean instance in ``auth``.

    If ``--domain`` is not set, the command looks for a ``domain`` module,
    then a ``subdomain`` module, in the current directory, then for
    ``src/*/domain.py``, then for ``src/*/subdomain.py``, as listed above.
    Within the module it imports, the command looks for a domain instance
    named ``domain`` or ``subdomain``, then for any domain instance.
