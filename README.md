# Protean

**Protean** is an opinionated Python framework for building event-driven applications with Domain-Driven Design — aggregates, CQRS, and event sourcing are first-class, and your domain logic stays independent of the database, broker, and API you run it on.

[![Python](https://img.shields.io/pypi/pyversions/protean?label=Python)](https://github.com/proteanhq/protean/)
[![Release](https://img.shields.io/pypi/v/protean?label=Release&style=flat-square)](https://pypi.org/project/protean/)
[![Build Status](https://github.com/proteanhq/protean/actions/workflows/ci.yml/badge.svg)](https://github.com/proteanhq/protean/actions/workflows/ci.yml)
[![Coverage](https://codecov.io/gh/proteanhq/protean/graph/badge.svg?token=0sFuFdLBOx)](https://codecov.io/gh/proteanhq/protean)
[![Tests](https://img.shields.io/badge/tests-10%2C386-brightgreen)](https://github.com/proteanhq/protean/actions/workflows/ci.yml)
[![Maintainability](https://img.shields.io/badge/maintainability-A-brightgreen)](https://docs.proteanhq.com/community/quality/)

## Installation

Protean is available on PyPI:

```console
$ pip install protean
```

Protean officially supports Python 3.11+.

## Quick Start

A command flows to its handler, the aggregate raises an event, and an event
handler reacts — all wired by the domain, independent of infrastructure:

```python
from protean import Domain
from protean.fields import Boolean, Identifier, String
from protean.utils.mixins import handle

domain = Domain(name="Publishing")
domain.config["command_processing"] = "sync"
domain.config["event_processing"] = "sync"


@domain.event(part_of="Post")
class PostPublished:
    post_id = Identifier()
    title = String()


@domain.aggregate
class Post:
    title = String(required=True, max_length=200)
    is_published = Boolean(default=False)

    def publish(self):
        self.is_published = True
        self.raise_(PostPublished(post_id=self.id, title=self.title))


@domain.command(part_of="Post")
class PublishPost:
    post_id = Identifier(identifier=True)
    title = String()


@domain.command_handler(part_of="Post")
class PostCommandHandler:
    @handle(PublishPost)
    def publish(self, command):
        post = Post(id=command.post_id, title=command.title)
        post.publish()
        domain.repository_for(Post).add(post)


@domain.event_handler(part_of="Post")
class Notifications:
    @handle(PostPublished)
    def announce(self, event):
        print(f"Published: {event.title}")


domain.init(traverse=False)
with domain.domain_context():
    domain.process(PublishPost(post_id="1", title="Hello, Protean"))
```

## Documentation

Online docs are available at [https://docs.proteanhq.com](https://docs.proteanhq.com).

## Quality

Protean is tested against 5 backing services across 4 Python versions on every commit.

| Metric | Value |
|---|---|
| Tests | 7,674 (3.0:1 test-to-code ratio) |
| Linting | Zero violations (Ruff) |
| Complexity | Avg 3.38 cyclomatic (A grade) |
| Maintainability | A rank (95% of files) |
| CI Matrix | Python 3.11-3.14 x PostgreSQL, Redis, Elasticsearch, MessageDB, MSSQL |

See the full [Quality Report](https://docs.proteanhq.com/community/quality/) for details.

## Contributing

> **Note**: Protean framework is not associated or related to [Protean eGov Technologies](https://www.proteantech.in/) or [Code for Gov Tech](https://codeforgovtech.in/) initiatives.

Protean is developed and maintained by a single maintainer. The contributions
that help most are **bug reports**, **real-world use cases**, and **adapter
packages** built against the public conformance suite.

- Found a bug or have a use case to share? [Open an issue](https://github.com/proteanhq/protean/issues). Clear, reproducible reports are the most valuable contribution you can make, and they are answered as a priority.
- Planning a non-trivial code change? Open an issue to discuss it first, before investing in a pull request. Unsolicited large PRs may not be merged. Small, obvious fixes are welcome directly.
- Building an adapter? Adapters live in their own packages, certified against the conformance suite. See the [contributing guide](https://docs.proteanhq.com/community/contributing/).

See [CONTRIBUTING.md](CONTRIBUTING.md) and the
[community](https://docs.proteanhq.com/community/) section for the full picture.

## License

Protean is licensed under the [Apache License 2.0](LICENSE).

**Licensing commitment.** The Protean framework core is, and will remain,
available under the Apache License 2.0. This is a permanent commitment: the
core will not be relicensed to a proprietary or source-available license.

Copyright 2018-2026 Subhash Bhushan C and the Protean contributors.
