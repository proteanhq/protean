---
hide:
  - toc
---

# Protean

Protean is a DDD and CQRS-based framework that helps you build Event-driven applications.

[![Release](https://img.shields.io/pypi/v/protean?label=Release&style=flat-square)](https://pypi.org/project/protean/)
[![Build Status](https://github.com/proteanhq/protean/actions/workflows/ci.yml/badge.svg)](https://github.com/proteanhq/protean/actions/workflows/ci.yml)
[![Coverage](https://codecov.io/gh/proteanhq/protean/graph/badge.svg?token=0sFuFdLBOx)](https://codecov.io/gh/proteanhq/protean)

## Overview

**Protean helps you build applications architected for change.**

At its core, Protean adopts a Domain-Driven Design (DDD) approach to
development, with support for patterns to succinctly and precisely express
your domain without worrying about technology aspects. When you are ready,
you can seamlessly plugin technologies like databases, message brokers, and
caches, and Protean will take care of the rest.

Protean is loosely based on these three paradigms:

- ***Service-Oriented*** - Develop your application as one or more subdomains that
can run independently as Microservices
- ***Event-Driven***: - Use events to propagate changes across aggregates and
subdomains to sync state within and across Bounded Contexts.
- ***Adapter-Based***: - A configuration-driven approach to specify technology
adapters, with multiple adapters supported out of the box.

## Features

<div class="grid cards" markdown>

-   __Rapid Prototyping__

    ---

    Prototype and rapidly iterate your domain model

-   __Technology Agnostic__

    ---

    Model your domain without worrying about technology choices

-   __Pluggable Adapters__

    ---

    Use a Configuration-based approach to specify technology choices

-   __Multi-domain Support__
    
    ---

    Evolve and structure bounded contexts over time

-   __Event-centric Communication__

    ---

    Use Domain Events to sync state across Aggregates and Bounded contexts

</div>

