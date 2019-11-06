.. _aggregate:

==========
Aggregates
==========

Aggregates are the coarse-grained building blocks of the domain model. Aggregates are the primary elements of a domain applying all behavior and data changes to the domain. Internally, Aggregates are groups of one or more Entities and Value Objects where they make sense. You designate one of those entities as the Aggregate Root.

The Root Entity is responsible for all other elements within the Aggregate. Put another way, all elements in the Aggregate are only accessible through the Root Entity. The name of the Root Entity usually mirrors the Aggregate’s name, so it is vital to choose a name that accurately describes the entire conceptual whole that the Aggregate represents.

.. testsetup:: *

    import os
    from protean.domain import Domain

    domain = Domain('Test')

    ctx = domain.domain_context()
    ctx.push()

.. testcode::

    from datetime import datetime

    from protean.core.field.basic import DateTime, String

    @domain.aggregate
    class Role:
        name = String(max_length=15, required=True)
        created_on = DateTime(default=datetime.today())

    role = Role(name='ADMIN')


Each Aggregate forms a transactional consistency boundary, meaning that within a single Aggregate, all elements must be consistent and satisfy associated business rules at the time of a transaction. The Aggregate should preferably satisfy all invariant rules all the time. This way, when the controlling transaction is committed to the database, the Aggregate should not need to check for conceptual validity.

Enclosing Entities and Value Objects into an Aggregate within a consistency boundary may seem easy, but this pattern is one of the least well understood amongst DDD technical guidelines.

The decisions around the transactional boundary should be business motivated because it is the business that determines what a valid state of the conceptual whole should be at any given time. In other words, if the Aggregate is not in a whole and valid state during persistence, the business operation is to be considered incorrect according to business rules.

This concept also means that as a general rule of Aggregate design, you should modify and commit only one Aggregate instance in one transaction. Move modifications to other Aggregates to a separate transaction.

The main point to remember is that business rules are the drivers for determining what must be whole, complete, and consistent at the end of a single transaction.

You can define abstract Aggregate structures that can be reused in multiple parts of the application. This is useful when an often repeating paradigm, like string `created` and `updated` timestamps, is present with all Aggregates in the system. You can inherit from the custom base Aggregate class, and all base attributes will be inherited.

.. testcode::

    from protean.core.aggregate import BaseAggregate
    from protean.core.field.basic import String

    class CustomBaseAggregate(BaseAggregate):
        foo = String(max_length=25)

        class Meta:
            abstract = True

    @domain.aggregate
    class ConcreteElement(CustomBaseAggregate):
        bar = String(max_length=25)

Rules
=====

**1. Protect Business Invariants inside Aggregate Boundaries**: The business should ultimately determine Aggregate compositions based on what must be consistent when a transaction is committed.

Within the aggregate boundary, all elements that are part of the composition have to satisfy business rules at all time. So if there are elements that can temporarily go out of sync with the rest of the structure, they should be outside the Aggregate's transaction boundary, however tempting it might be to include them. Typical reasons to include them would be to maintain data consistency and also to avoid using eventual consistency mechanisms (refer to Rule #2 for an in-depth explanation).

However, the wrong transactional boundary can produce an incorrect design and create unnecessary coupling between two different concepts which do not have the same set of invariants.

**2. Use Eventual Consistency outside the Aggregate Boundary**: Each transaction should only handle one single aggregate instance. Other Aggregate changes are performed as part of a different transaction.

However, it is common to make changes across multiple Aggregates as part of a domain change. If each Aggregate represents a transactional boundary, how do we ensure that changes remain consistent across Aggregates?

Domain events to the rescue. Aggregates publish Domain Events on domain-meaningful changes, and other Aggregates who are interested in the event subscribe to it. The messaging mechanism delivers the Domain Events to interested parties through subscriptions.  When the domain event makes its way to an interested subscriber, a brand new transaction is started for the changes to the related Aggregate and committed.

The interested Bounded Context can be in the same one Bounded Context as the Domain Event, or it could be in a different BC. Even when you have both the publisher and the subscriber in the same Bounded Context, it makes sense to use the messaging middleware if you already use it for publishing to other Bounded Contexts.

If you are in the initial stages of your project and have not invested in a messaging infrastructure, you can commit changes to multiple aggregates in a single transaction but should still use Domain events to publish changes. You can use a Unit of Work pattern to group all changes to be committed together.

This initial setup allows you to get used to the techniques without taking too big an initial step. Just understand that this is not the primary way of using Aggregates, and you may experience transactional failures as a result.

Over time, you can introduce message brokers and change the underlying mechanism to be asynchronous with multiple transactions, following the rules of eventual consistency.

**3. Reference other Aggregates by Identity**: Most practical applications need to link aggregates somehow to perform domain changes. When that happens, use unique identifiers to link aggregates.

This rule ensures that Aggregates remain small and prevents reaching out to modify multiple Aggregates in the same transaction. This guideline further helps keep the Aggregate design small and efficient, making for lower memory requirements and quicker loading from a persistence store. It also helps enforce the rule not to modify other Aggregate instances within the same transaction. With only identifiers of other Aggregates, there is no easy way to obtain a direct object reference to them.

Another benefit to using reference by identity only is that you can store your Aggregates in just about any kind of persistence mechanisms, such as relational database, document database, key-value store, and data grids/fabrics. You have options to use relational databases, JSON-based stores such as PostgreSQL or MongoDB, and even index stores like Elasticsearch.

**4. Design Small Aggregates**: To ensure transactional boundary and to keep your aggregate transactions fast and nimble, restrict the maximum possible size of your aggregates to be on the smaller side.

The memory footprint and transactional scope of each Aggregate should be relatively small, to ensure transactional success. This rule also has the added benefit that each Aggregate is more natural to work on because a single developer manages all associated tasks. Small Aggregates mean they are easier to test too. The size of your Aggregate can also indicate design problems with your application. If your Aggregate is trying to do too many things, it is likely not following the Single Responsibility Principle (SRP), and this problem shows up in its size.

Notes
=====

Abstraction
-----------

Every good software model has a set of abstractions that address the business’s way of doing things. Good programming practices advocate creating these abstractions in code, to keep the codebase DRY and small. However, it is easy to take this concept too far and abstract everything possible. You should choose the appropriate level of abstraction for each concept being modeled, without making things abstract for the sake of abstraction.

You generally end up creating the proper abstractions if you follow the direction of your Ubiquitous Language. It’s much easier to model the abstractions correctly because it is the Domain Experts who convey at least the genesis of your modeling language. Without this guideline, the language of the software model does not match the mental model of the Domain Experts. You also run a risk of abstracting aspects that are different in the first place and running into trouble later when you get down to implementation details of each type.

Avoid the trap of DRYing code in the name of abstractions. Model your software codebase to follow the Ubiquitous language carefully, and you end up with a practical design of the domain model automatically.

Atomicity
---------

Be careful that the business doesn’t insist that every Aggregate fall within the 3a specification (immediate consistency). While that makes sense to end-users, it may not always be the right design.

The push towards atomicity may be especially strong when many in the design session have a background in database design and data modeling. Those stakeholders tend to have a very transaction-centered point of view. However, it is doubtful that the business needs immediate consistency in every case.

Proving how transactions fail due to concurrent updates by multiple users and the memory overhead taken by such large-cluster designs can help convince stakeholders to move away from a data model oriented thought process.

This exercise indicates that eventual consistency is business-driven, not technology-driven. Of course, you have to find a way to support eventual updates between multiple Aggregates technically. Even so, it is only the business that can determine the acceptable time frame for updates to occur between various Entities. Some are immediate, or transactional, which means the same Aggregate must manage them. Some are eventual, which means they may be managed through Domain Events and messaging, for example.

Considering what the business would have to do if it ran its operations only employing paper systems, can provide some worthwhile insights into how various domain-driven operations should work within a software model of the business operations.

Testability
-----------

You should design your Aggregates to have sound encapsulation for unit testing. Complex Aggregates are hard to test. Following the previous design guidance can help you model testable Aggregates.

Development of the unit tests usually follows the creation of scenario specification acceptance tests, concentrating on tests that check that the Aggregate correctly does what it is supposed to do. All possible operations are to be tested to ensure the correctness, quality, and stability of the Aggregates, thus ensuring complete confidence in the business functionality.
