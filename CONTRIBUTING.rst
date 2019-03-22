=======================
Contributing to Protean
=======================

You are awesome! Thanks for taking the time to contribute!

What follows is a set of guidelines for contributing to Protean and its related packages, which are hosted in the Protean Organization on GitHub. These are mostly guidelines, not rules. Use your best judgment, and feel free to propose changes to this document in a pull request.

Code of Conduct
---------------

This project and everyone participating in it is governed by the :ref:`Code of Conduct <code-of-conduct>`. By participating, you are expected to uphold this code. Please report unacceptable behavior to <subhash.bhushan@gmail.com>.

General Guidelines
------------------

Be Nice
^^^^^^^

Protean is a safe community. **All contributions are welcome**, as long as
everyone involved is treated with respect.

.. _early-feedback:

Get Early Feedback
^^^^^^^^^^^^^^^^^^

If you are contributing, do not feel the need to sit on your contribution until
it is perfectly polished and complete. It helps everyone involved for you to
seek feedback as early as you possibly can. Submitting an early, unfinished
version of your contribution for feedback in no way prejudices your chances of
getting that contribution accepted, and can save you from putting a lot of work
into a contribution that is not suitable for the project.

Contribution Suitability
^^^^^^^^^^^^^^^^^^^^^^^^

Our project maintainers have the last word on whether or not a contribution is
suitable for Protean. All contributions will be considered carefully, but from
time to time, contributions will be rejected because they do not suit the
current goals or needs of the project.

If your contribution is rejected, don't despair! As long as you followed these
guidelines, you will have a much better chance of getting your next
contribution accepted.

Code Contributions
------------------

Bug reports
^^^^^^^^^^^

Before you raise one, though, please check through the `GitHub issues`_, 
**both open and closed**, to confirm that the bug hasn’t been reported before. 
Duplicate bug reports are a huge drain on the time of other contributors, 
and should be avoided as much as possible.

When `reporting a bug <https://github.com/proteanhq/protean/issues>`_ please include:

    * Your operating system name and version.
    * Any details about your local setup that might be helpful in troubleshooting.
    * Detailed steps to reproduce the bug.

Documentation improvements
^^^^^^^^^^^^^^^^^^^^^^^^^^

Protean could always use more documentation, whether as part of the
official Protean docs, in docstrings, or even on the web in blog posts,
articles, and such. The documentation files live in the docs/ directory of the codebase. 
They’re written in reStructuredText, and use Sphinx to generate the full suite of documentation.

When contributing documentation, please do your best to follow the style of the 
documentation files. This means a soft-limit of 79 characters wide in your text files 
and a semi-formal, yet friendly and approachable, prose style.

When presenting Python code, use single-quoted strings ('hello' instead of "hello").

All Documentation changes will need to go through 
the normal pull request process.

Feature requests and feedback
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The best way to send feedback is to file an issue at `GitHub issues`_.

If you are proposing a feature:

* Explain in detail how it would work.
* Keep the scope as narrow as possible, to make it easier to implement.
* Remember that this is a volunteer-driven project, and that code contributions are welcome :)

Development
^^^^^^^^^^^

To set up `protean` for local development:

1. Fork `protean <https://github.com/proteanhq/protean>`_
   (look for the "Fork" button).
2. Clone your fork locally::

    git clone git@github.com:your_name_here/protean.git

3. Create a branch for local development::

    git checkout -b name-of-your-bugfix-or-feature

   Now you can make your changes locally.

4. When you're done making changes, run all the checks, doc builder and spell checker with `tox <http://tox.readthedocs.io/en/latest/install.html>`_ one command::

    tox

5. Commit your changes and push your branch to GitHub::

    git add .
    git commit -m "Your detailed description of your changes."
    git push origin name-of-your-bugfix-or-feature

6. Submit a pull request through the GitHub website.

Pull Request Guidelines
^^^^^^^^^^^^^^^^^^^^^^^

If you need some code review or feedback while you're developing the code just make the pull request.

For merging, you should:

1. Include passing tests (run ``tox``) [1]_.
2. Update documentation when there's new API, functionality etc.
3. Add a note to ``CHANGELOG.rst`` about the changes.
4. Add yourself to ``AUTHORS.rst``.

.. [1] If you don't have all the necessary python versions available locally you can rely on Travis - it will
       `run the tests <https://travis-ci.org/proteanhq/protean/pull_requests>`_ for each change you add in the pull request.

       It will be slower though ...

Tips
^^^^

To run a subset of tests::

    tox -e envname -- pytest -k test_myfeature

To run all the test environments in *parallel* (you need to ``pip install detox``)::

    detox

Code Review
^^^^^^^^^^^

Contributions will not be merged until they've been code reviewed. You should
implement any code review feedback unless you strongly object to it. In the
event that you object to the code review feedback, you should make your case
clearly and calmly. If, after doing so, the feedback is judged to still apply,
you must either apply the feedback or withdraw your contribution.

New Contributors
^^^^^^^^^^^^^^^^

If you are new or relatively new to Open Source, welcome! Protean aims to
be a gentle introduction to the world of Open Source. If you're concerned about
how best to contribute, please drop a mail to <subhash.bhushan@gmail.com> asking for help.

Please also check the :ref:`early-feedback` section.

.. _GitHub issues: https://github.com/proteanhq/protean/issues