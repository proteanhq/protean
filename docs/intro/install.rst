.. _install:

Installation
============

This part of the documentation covers the installation of Protean.


$ pip install protean
-------------------------

To install Protean, simply run this simple command in your terminal of choice::

    $ pip install protean

We highly recommend |pyenv| to install multiple Python versions side-by-side, which does not interfere with system-default Python installations.


Get the Source Code
-------------------

Protean is actively developed on GitHub, where the code is |protean-github|.

You can either clone the public repository::

    $ git clone git://github.com/proteanhq/protean.git

Or, download the `tarball <https://github.com/proteanhq/protean/tarball/master>`_::

    $ curl -OL https://github.com/proteanhq/protean/tarball/master
    # optionally, zipball is also available (for Windows users).

Once you have a copy of the source, you can embed it in your own Python
package, or install it into your site-packages easily::

    $ cd protean
    $ pip install .


.. |pyenv| raw:: html

    <a href="https://github.com/pyenv/pyenv" target="_blank">pyenv</a>

.. |protean-github| raw:: html

    <a href="https://github.com/proteanhq/protean" target="_blank">always available</a>