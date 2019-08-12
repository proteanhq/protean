.. _repository:

============
Repositories
============

These collection-like objects are all about persistence. Every persistent Aggregate type will have a Repository. Generally speaking, there is a one-to-one relationship between an Aggregate type and a Repository.

A Repository is responsible for persisting and loading an aggregate as well as all elements in the aggregate's composition.

Strictly speaking, only Aggregates have Repositories. If you are not using Aggregates in a given Bounded Context for whatever reason, the Repository pattern may not be useful to you.
