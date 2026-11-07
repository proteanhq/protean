# Setting up Protean locally

This guide is for collaborators, adapter authors, and anyone who wants to run
Protean from source. Only collaborators can open pull requests on Protean.
[CONTRIBUTING](https://github.com/proteanhq/protean/blob/main/CONTRIBUTING.md)
explains how to propose a change.

## First time local setup

- Download and install [git](https://git-scm.com/downloads).
- Configure git with your `username`_ and `email`.

```sh
$ git config --global user.name 'your name'
$ git config --global user.email 'your email'
```

- Make sure you have a [GitHub account](https://github.com/join).
- [Clone](https://docs.github.com/en/repositories/creating-and-managing-repositories/cloning-a-repository) the repository locally.

```sh
$ git clone https://github.com/proteanhq/protean
$ cd protean
```

- Install [uv](https://docs.astral.sh/uv/getting-started/installation/).

```sh
$ curl -LsSf https://astral.sh/uv/install.sh | sh
```

- Install development dependencies. uv will automatically create a virtual environment in `.venv`.

```sh
$ uv sync --all-extras --all-groups
```

-   Install pre-commit hooks.

```sh
$ pre-commit install --install-hooks
```

- The `postgresql` extra installs psycopg 3 with its pre-compiled binary package, and the `postgresql-psycopg2` extra installs `psycopg2-binary`. `--all-extras` installs both, so the test suite can run on either driver. Neither needs system dependencies.

## Start coding

- Create a branch off `main` for the issue you are working on.

```sh
$ git fetch origin
$ git checkout -b your-branch-name origin/main
```

- Using your favorite editor, make your changes, [committing as you go](
        https://afraid-to-commit.readthedocs.io/en/latest/git/commandlinegit.html#commit-your-changes).
- Include tests that cover any code changes you make. Make sure the test fails
without your patch. Run the tests as described below.
- Push your branch to GitHub and [create a pull request](
        https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/
        proposing-changes-to-your-work-with-pull-requests/creating-a-pull-request).
- Link to the issue being addressed with `fixes #123` or `closes #123` in the pull request.

```sh
$ git push --set-upstream origin your-branch-name
```

## Running Tests

Run the basic test suite with:

```sh
$ protean test
```

This runs the basic tests for the current environment. To run  the full test suite, you can set up
dependent services locally with docker:

```sh
$ make up
...
docker-compose up -d redis elasticsearch postgres message-db
[+] Running 4/4
 ✔ Container protean-postgres-1       Running
 ✔ Container protean-elasticsearch-1  Running
 ✔ Container protean-message-db-1     Running
 ✔ Container protean-redis-1          Running
...
$ protean test -c FULL
...
```

!!! note "Any OCI container engine works, not just Docker"
    These services run on any OCI-compatible container engine. Protean's test
    harness connects to the service ports on `localhost`, so it works with any
    tool that starts the containers. [OrbStack](https://orbstack.dev),
    [Podman](https://podman.io), [Colima](https://github.com/abiosoft/colima),
    and Rancher Desktop all work with the same `docker-compose.yml`. For Podman,
    run `podman compose` directly or point `docker-compose` (or `docker compose`) at the Podman socket
    via `DOCKER_HOST`.

Running a full test will also generate a coverage report as part of test
output. An uncovered line is a good place to start contributing: find the
behaviour that runs it and test that behaviour (see
[Do not write a test only to reach a line](testing.md#do-not-write-a-test-only-to-reach-a-line)).

For more detailed information about testing, please refer to the [Testing Guide](testing.md).
