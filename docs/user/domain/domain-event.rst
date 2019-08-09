.. _domain-events:

=============
Domain Events
=============

A Domain Event is a record of some business-significant occurence in a Bounded Context. Domain Events help make strategic design possible, by providing the ability for Bounded Contexts to remain distinct, but also communicate effectively. Domain Events are very much a part of the Core Domain, and are identified frequently from the domain's Ubiquitous Language.

When Events are delivered to interested parties, in the same bounded context, other bounded contexts or even external systems, they are generally used to facilitate eventual consistency. Such a design can eliminate the need for two-phase commits (global transactions) and support the invariant rules defined in Aggregates.

One rule of Aggregates states that only a single instance should be modified in a single transaction, and all other dependent changes must occur in separate transactions. So other Aggregate instances in the local Bounded Context may be synchronized using this approach. Remote dependencies can be bought to a consistent state with latency with the same approach. This kind of decoupling helps provide a highly scalable and optimized set of services, that work well with each other, but are still loose coupled.

It is also important to remember that there will be a whole of events in the application that the domain experts or the business do not really care about. Still, it is possible that Events will be more prolific than domain experts directly require, purely because of technical requirements. It is usually recommended that business events are annotated for easy recognition.

Notes
=====

* Domain Event objects should be immutable in nature, and should support side-effect free functions.
* The Domain Event's name should preferably be indicative of a past occurrence; that is, the names should be verbs in the past-tense.
* The Domain Model should not be exposed to the messaging infrastructure. An event should be submitted to the domain, and it should be the domain's responsibility to transport it to subscribers.
* Domain Events should include all the necessary information from the originating aggregate, including it's unique identity. It is preferable to not have to contact the originating aggregate bounded context for additional information.
