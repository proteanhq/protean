.. _api-repository:

============
Repositories
============


A primary function of the repository is to be a representative of domain functionality. In that sense, it contains methods and implementations that cleary identify what the domain is trying to ask/do with the persistence store.

A repository works in conjuction with the DAO layer to operate on the persistence store. This differentiation is necessary because the DAO is a concrete implementation per persistence store and is built as a plugin to Protean. But a repository is representative of the domain layer and remains unchanged with changing underlying persistence store implementations.
