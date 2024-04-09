# Domain Discovery

In most cases, you will use the `protean` script to interact with your domain 
over the CLI. The script must be told where to find your domain to load and 
initialize it, prepping it for your use. The `--domain` option is used to 
specify how to load the domain.

While `--domain` supports a variety of options for specifying your domain, 
the below typical values cover most use cases:

**(nothing)**

A "domain" or "subdomain" is imported (as a ".py" file, or package),
automatically detecting a domain (``domain`` or ``subdomain``).

**`--domain auth`**

The given name is imported, automatically detecting a domain (``domain`` or
``subdomain``).

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

    If ``--domain`` is not set, the command will try to import "domain" or
    "subdomain" (as a ".py" file, or package) and try to detect an Protean
    instance. Within the given import, the command looks for an domain instance
    named ``domain`` or ``subdomain``, then any domain instance.