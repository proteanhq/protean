Command Line Interface
======================

Installing Protean installs the ``protean`` script, a `Click`_ command line
interface, in your virtualenv. Executed from the terminal, this script gives
access to built-in, extension, and application-defined commands. The ``--help``
option will give more information about any commands and options.

.. _Click: https://click.palletsprojects.com/


Application Discovery
---------------------

The ``protean`` command is installed by Protean, not your application; it must be
told where to find your application in order to use it. The ``PROTEAN_DOMAIN``
environment variable is used to specify how to load the application.

.. tabs::

   .. group-tab:: Bash

      .. code-block:: text

         $ export PROTEAN_DOMAIN=shipping
         $ protean server

   .. group-tab:: CMD

      .. code-block:: text

         > set PROTEAN_DOMAIN=shipping
         > protean server

   .. group-tab:: Powershell

      .. code-block:: text

         > $env:PROTEAN_DOMAIN = "shipping"
         > protean server

While ``PROTEAN_DOMAIN`` supports a variety of options for specifying your
application, most use cases should be simple. Here are the typical values:

(nothing)
    The name "domain" or "subdomain" is imported (as a ".py" file, or package),
    automatically detecting an app (``domain`` or ``subdomain``).

``PROTEAN_DOMAIN=shipping``
    The given name is imported, automatically detecting a domain (``domain``
    or ``subdomain``).

----

``PROTEAN_DOMAIN`` has three parts: an optional path that sets the current working
directory, a Python file or dotted import path, and an optional variable
name of the instance or factory. If the name is a factory, it can optionally
be followed by arguments in parentheses. The following values demonstrate these
parts:

``PROTEAN_DOMAIN=src/shipping``
    Sets the current working directory to ``src`` then imports ``shipping``.

``PROTEAN_DOMAIN=shipping.domain``
    Imports the path ``shipping.domain``.

``PROTEAN_DOMAIN=shipping:dom2``
    Uses the ``dom2`` Flask instance in ``shipping``.


If ``PROTEAN_DOMAIN`` is not set, the command will try to import "domain" or
"subdomain" (as a ".py" file, or package) and try to detect a domain instance.

Within the given import, the command looks for a domain instance named
``domain`` or ``subdomain``, then any domain instance.

Run the Development Server
--------------------------

The :func:`server <cli.server>` command will start the background development server::

    $ protean server
     * Starting server...
