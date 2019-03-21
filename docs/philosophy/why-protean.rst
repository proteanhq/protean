.. _why-protean:

Why Protean?
============

Would you buy a car if someone told you that you would have to replace the entire car if you tear a chair cushion?

We see plenty of examples around us of design architectures built for flexibility and maintainability:

* Components work very well with each other yet are not tightly coupled. You can disassemble most of them, though disassembling some may be vastly more complex than others (Say an automobile engine)
* Each component adheres to a well-understood, well-published contract. So as long as the "contract" is fulfilled, a component can be replaced with its competitor's parts.

You see this feature repeating in most physical products - Cars, Laptops, Furniture, Kitchen Equipment and the list goes on. Want to enter a market for rubber gaskets? Just look up the contract (dimensions, quality, durability, etc.), fulfill them in your product at the lowest cost possible, and you are on. Marketing your product to get into the hands of the consumer is an entirely different story, but creating a new product is relatively simple.

This thought process does exist in the software industry, but to a far lesser extent.

We see this breakage when we try to switch to a new technology because it has made a task cheaper/simpler, or a competitor because he is offering better rates or better functionality, or simply because a component is outdated and non-maintained. As a developer, you would typically spend more time rewriting code to switch to the new component, than you spent actually writing it in the first place. More importantly,you probably will expend the same effort when you decide to switch the component again in the future.

Most of us have developed applications, for everything from weekend projects to SaaS software, using popular frameworks meant to ease our development effort and reduce our go-live time. The frameworks promise shorter timeframes and better output, and deliver on the promise more often than not. But when we attempt to take the same knowledge and build an application to address the needs of a complex domain, things tend to break down. Such applications tend to have long product cycles, usually over multiple years, and also evolve over time as we go deeper and deeper into the domain.

To our chagrin, we discover that while we were able to get the first version of the product out of the door relatively quickly, things tend to become complicated over time. And instead of speeding up as we discover and understand more about the business, development tends to slow down and get costlier. In extreme cases, the product can literally come to a stand still with developers just to trying to fight entropy and keep the product running.

Protean was built with the vision of providing a clear path to creating and maintaining such complex applications. In that sense, it is a Thought framework rather than a technology framework. It advocates a domain-centric thought process, usage of well-thought design patterns, code organization, separation of concerns and adopting a common language spoken by all stakeholders of a project. The technology constructs offered are a means to and end, to make the above facets possible.

Protean has two flavors to it:
* It can be used to develop Domain Centric Applications, backed by a Ubiquitous language shared among Developers and Business Experts
* It can be used as a Clean Architecture Framework, to create Technology/Infrastructure agnostic applications

Irrespective of which option you use Protean for, you end up with cutting-edge practices that will help you develop long-term complex software, like:

* Independence from underlying Technologies like Database, API Frameworks and Message brokers
* Established Design Patterns to organize your code for maintainability
* 100% Testability of your business logic

Protean as a Domain-Driven Design Framework
-------------------------------------------

Domain-Driven Design is a software development technique that places the understanding of customer’s problem domain at the heart of software. It is a bundle of both technical ideas as well as a reliable process structure the creativity in the development cycle.

Protean helps drive this creative process, assisting the developers and business experts to converge on a Domain Model, using a common Ubiquitous language. It relieves the developer of the burden to develop an end-to-end prototype in the product and allows him to focus on mirroring the domain model in the product, tested with real use-cases and gathering feedback along the way. It strengthens the iterative process of model refinement until the domain model adequately reflects the problem domain, focusing on the important aspects and leaving out irrelevant ones.

The unimportant aspects during model refinement include infrastructure details like database, API framework, storage, etc. Protean lets you refine the model first and then plugin an infrastructure component dynamically into the codebase. By virtue of delaying infrastructure decisions until needed, developers tend to make a more informed decision of the correct technology appropriate for the problem statement.

Protean is also pragmatic at the same time. It does not ignore or skirt-around realities of performance or technology limitations, and tries to provide a wide variety of options to address realworld, production concerns.

Protean as a Clean Architecture Framework
-----------------------------------------

Clean Architecture is not a new idea. There have been similar architectures outlined by various people like, Hexagonal Architecture, Onion Architecture, Screaming Architecture, and Lean Architecture.

Though these architectures vary to some extent in their details, they are all focused on the single goal of separation of concerns. They achieve this separation by dividing the codebase into layers. Each has at least one layer designated for business rules, and one or more layers for interfaces to infrastructure technology.

An application built with Clean Architecture system is 

* **Independent of Frameworks**: Application does not depend on the existence of some library of feature laden software. This allows the application to use such frameworks as tools, rather than having to shoe-horn the functionality into their limited constraints.
* **Testable**: The Application's business rules can be tested without the UI, Database, Web Server, or any other external element, making it faster, dependable and resitant to external changes
* **Independent of UI or database constraints**: The UI of the application (or UIs, if multiple channels like Mobiles are involved) can change easily, without needing any changes to the rest of the system. A user should be able to use a console UI, in need be, without changing the business rules. Similarly, the application's business rules are not bound to the database. You can swap out one SQL database for another, or even switch to a NoSQL DB like Mongo, BigTable, CouchDB or Elasticsearch.
* **Independent of any external agency**: The application is basically agnostic to the outside world. The business rules simply don’t know anything at all about what it's like out there.

By being independent, an application allows developers to delay long-term decisions until the last possible moment.

A long term decision is any part of the design that needs considerable time and effort to change, like the choice of a database or a web framework, or even the data format of messages between the backend and the UI. The last possible moment is any time frame beyond which not making a decision results in diminishing returns or declining productivity. As they say, sometime's a bad decision is much better than no decision at all.

But the real beauty of a Clean Architecture compliant application would be that even after you have taken long-term decisions at the last possible moment, you can still go back to the blackboard and start anew, without spending a ton of time and effort. That's where interface definitions play a critical role. As long as your components adhere to the contract published by the application, you can switch between them freely and often, on the fly.

Protean is geared to get you on board the Clean Architecture wagon from day one. It was built based on learning and feedback while building applications for realworld clients. Unknown requirements, changing technology landscape, improved API communication and ever tighter deadlines pushed us to wonder if there was a way to build an application where all these factors could be addressed. Where we could actually go back on a decison and switch to a better solution in the middle of a project, without costing the project a tooth or a limb.

Protean is geared for flexibility and maintainability for the long run.

More on clean architecture has been outlined in |uncle-bob-article|.

.. |uncle-bob-article| raw:: html

    <a href="http://blog.cleancoder.com/uncle-bob/2012/08/13/the-clean-architecture.html" target="_blank">Uncle Bob's article</a>
