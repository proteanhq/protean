# Domain Discovery

In most cases, you will use the `protean` script to interact with your domain
over the CLI. You tell the script where to find your domain. The script then
loads and initializes the domain so it is ready for use. The `--domain` option
is used to specify how to load the domain.

While `--domain` supports a variety of options for specifying your domain,
the below typical values cover most use cases:

**(nothing)**

The script imports a module named "domain" or "subdomain" (as a ".py" file, or
package). The script then detects the domain instance in it (``domain`` or
``subdomain``).

**`--domain auth`**

The script imports the module you name, here `auth`, and detects the domain
instance in it (``domain`` or ``subdomain``).

!!! note

    ``--domain`` has three parts: an optional path that sets the current working
    directory, a Python file or dotted import path, and an optional variable
    name of the instance. The following values demonstrate these
    parts:

    - ``--app src/auth``
        Sets the current working directory to ``src`` then imports ``hello``.

    - ``--app auth.domain``
        Imports the path ``auth.domain``.

    - ``--app auth:sso``
        Uses the ``sso`` Protean instance in ``auth``.

    If ``--domain`` is not set, the command tries to import "domain" or
    "subdomain" (as a ".py" file, or package). The command then tries to detect
    a Protean instance in that import. Within the given import, the command
    looks for an domain instance named ``domain`` or ``subdomain``, then any
    domain instance.
