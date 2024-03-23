# Protean

*Framework for Event-driven Applications - build to last, batteries included*

---

**Documentation**: <a href="https://docs.proteanhq.com" target="_blank">https://docs.proteanhq.com</a>

**Source Code**: <a href="https://github.com/proteanhq/protean" target="_blank">https://github.com/proteanhq/protean</a>

---

Protean is a DDD and CQRS-based framework that helps you build Event-driven applications.

## Overview

Protean helps you build applications that can scale and adapt to growing requirements without significant rework.

At its core, Protean encourages a Domain-Driven Design (DDD) approach to development, with support for artifacts necessary to express your domain succinctly and precisely. It also allows you to remain agnostic to the underlying technology by keeping implementation details out of view.

Protean can be thought of having three capabilities:

- *Service-Oriented* - Develop your application as one or more subdomains that run independently as Microservices
- *Event-Driven*: - Use events to propagate changes across subdomains or become eventually consistent within a Bounded Context.
- *Adapter-based*: - Use Remain technology-agnostic by exposing Port interfaces to the infrastructure, with multiple adapters supported out of the box.
