# Contribute to Protean

Thank you for considering contributing to Protean!

## First time local setup

- Download and install [git](https://git-scm.com/downloads).
- Configure git with your `username`_ and `email`.

```sh
$ git config --global user.name 'your name'
$ git config --global user.email 'your email'
```

- Make sure you have a [GitHub account](https://github.com/join).
- Fork Protean to your GitHub account by clicking the [fork](https://github.com/proteanhq/protean/fork) button.
- [Clone](https://docs.github.com/en/github/getting-started-with-github/fork-a-repo#step-2-create-a-local-clone-of-your-fork) the main repository locally.

```sh
$ git clone https://github.com/proteanhq/protean
$ cd protean
```

- Add your fork as a remote to push your work to. Replace `username` with your GitHub username. This names the remote "fork", the default Protean remote is "origin".

```sh
$ git remote add fork https://github.com/{username}/protean
```

- [Create and activate virtualenv](https://docs.python.org/3/library/venv.html#creating-virtual-environments).

```sh
$ python3 -m venv .venv
$ source .venv/bin/activate
```

- Install the development dependencies.

```sh
$ poetry install --with dev,test,docs,types --all-extras
```

-   Install the pre-commit hooks.

```sh
$ pre-commit install --install-hooks
```

## Start coding

- Create a branch to identify the issue you would like to work on. If
    you're submitting a bug or documentation fix, branch off of the
    latest ".x" branch.

```sh
$ git fetch origin
$ git checkout -b your-branch-name origin/0.11.x
```

If you're submitting a feature addition or change, branch off of the
    "main" branch.

```sh
$ git fetch origin
$ git checkout -b your-branch-name origin/main
```

- Using your favorite editor, make your changes, [committing as you go](
        https://afraid-to-commit.readthedocs.io/en/latest/git/commandlinegit.html#commit-your-changes).
- Include tests that cover any code changes you make. Make sure the test fails
without your patch. Run the tests as described below.
- Push your commits to your fork on GitHub and [create a pull request](
        https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/
        proposing-changes-to-your-work-with-pull-requests/creating-a-pull-request).
- Link to the issue being addressed with `fixes #123` or `closes #123` in the pull request.

```sh
$ git push --set-upstream fork your-branch-name
```

## Running Tests

Run the basic test suite with:

```sh
$ protean test
```

This runs the basic tests for the current environment, which is usually
sufficient. If you want to run  the full test suite, you can sep up
dependent services locally with docker:

```sh
$ make up
$ protean test -c FULL
```

Running a full test will also generate a coverage report as part of test
output. Writing tests for lines that do not have coverage is a great way to
start contributing.
