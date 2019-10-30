.. _why-protean:

============
Why Protean?
============

Would you buy a car if you knew you would need to replace the entire car if you tear a chair cushion?

We see plenty of things around us built for flexibility, maintainability,  and interoperability:

* Components work very well with each other with no tight coupling. You can take apart most of them, though disassembling some may be vastly more complex than others (Say an automobile engine)
* Each component adheres to a well-understood, well-published contract. So as long as a component fulfills the "contract," it can replace a competitor's parts.

You see this feature repeating in most physical products - Cars, Laptops, Furniture, Kitchen Equipment, and the list goes on. Want to enter a market for rubber gaskets? Just look up the contract (like dimensions, quality, and durability), fulfill them in your product at the lowest cost possible, and you are on.

This thought process is present in the software industry, but not as prevalent as it should be.

We see this in action when we try to switch to new technology because it makes a task cheaper/simpler, or to a competitor's product because he is offering better rates or better functionality, or simply because a component is outdated and not maintained. You would probably end up spending more time rewriting code to switch to the new component than you spent writing it in the first place! More importantly, switching to another component in the future costs the same amount of effort, or even more!

Most of us have developed applications for everything from weekend projects to Enterprise SaaS software, using popular frameworks meant to ease our development effort and reduce our go-live time. These frameworks promise shorter time frames and better output and deliver on the promise more often than not. But when we attempt to take the same knowledge and build an application to address the needs of a complex domain, things tend to break down. Such applications tend to have long product cycles, go through radical changes, and evolve as we dig deeper and deeper into the domain.

To our dismay, we discover that while we were able to get the first version of the product out of the door relatively quickly, things tend to become complicated over time. And instead of speeding up, development tends to slow down and get costlier. In extreme cases, the development can come to a standstill with developers just to trying to fight the bugs and side-effects, and keep the product running.

Protean's vision is to provide a clear path to create and maintain such complex applications. In that sense, it is more a thought framework rather than a technology framework. It advocates a domain-centric thought process, usage of well-thought design patterns, code organization, separation of concerns, and adopting a common language spoken by all stakeholders of a project. Its technology constructs are a means to an end, to make the above possible.

Protean has two flavors to it:
* It can be used to develop Domain Centric Applications, backed by a Ubiquitous language shared among Developers and Business Experts
* It can be used as a Technology-agnostic Framework, to create and sustain software over a long time

Irrespective of which option you use Protean for, you end up with cutting-edge practices that help you develop long-term sophisticated software, like:

* Independence from underlying Technologies like Database, API Frameworks, and Message brokers
* Established Design Patterns to organize your code for maintainability
* 100% Testability of your business logic

As a Domain-Driven Design Framework
===================================

Domain-Driven Design is a software development technique that places the understanding of a customer's problem domain at the heart of software. It is a bundle of both technical ideas, as well as good patterns to be used during development.

Protean helps drive this creative process, assisting the developers and business experts in converging on a Domain Model, using a common Ubiquitous Language. It relieves the developer of the burden to develop an end-to-end prototype in the product. It allows him to focus on mirroring the domain model in the product, tested with real use-cases, and gathering feedback along the way. It strengthens the iterative process of model refinement until the domain model adequately reflects the problem domain.

Secondary aspects that are infrastructure details like database, API framework, and storage can be "plugged in" dynamically into the codebase. By delaying infrastructure decisions until needed, developers tend to make a more informed decision on the correct technology appropriate for their domain's problem statement.

Protean is also pragmatic at the same time. It does not ignore or skirt-around realities of performance or technology limitations and tries to provide a wide variety of options to address real-world, production concerns.

As a Technology-Agnostic Framework
==================================

Protean organizes infrastructure code in the form of Ports and Adapters.

Being technology-agnostic is not a new idea. Many architectures like Hexagonal Architecture, Onion Architecture, Screaming Architecture, and Lean Architecture, advocate the focus on domain development while ignoring technology aspects. They are all focused on the single goal of separation of concerns. They achieve this separation by dividing the codebase into layers. Each has at least one layer designated for business rules and one or more layers for interfaces to infrastructure technology.

An application built these principles tends to be:

* **Independent of Frameworks**: Application does not depend on the existence of some library of feature-laden software. Frameworks become tools, avoiding the need to shoe-horn the functionality to fit them.
* **Testable**: The Application's business rules can be tested without the UI, Database, Web Server, or any other external element, making it faster, dependable and resistant to external changes
* **Independent of UI or database constraints**: The UI of the application (or UIs, if multiple channels like Mobiles are involved) can change quickly, without needing any changes to the rest of the system. A user should be able to use a console UI, in need be, without changing the business rules. Similarly, the application's business rules are not bound to the database. You can swap out one SQL database for another, or even switch to a NoSQL DB like Mongo, BigTable, CouchDB or Elasticsearch.
* **Independent of any external agency**: The application is agnostic to the outside world. The business rules don't know anything about the infrastructure running the application.

By being independent of technology, an application allows developers to delay long-term decisions until the Last Responsible Moment (LRM).

But the real beauty of such applications would be that even after you have taken critical decisions, you can still go back to the blackboard and start anew, without spending a ton of time and effort. That's where interface definitions play a critical role. As long as your components adhere to the contract published by the application, you can switch between them freely and often, on the fly.

Protean is geared to get you onboard the Ports and Adapters wagon from day one. It is built based on learning and feedback while building applications for real-world clients. Unknown requirements, an ever-changing technology landscape, improved API communication, and ever tighter deadlines pushed us to wonder if there was a way to build an application where all these factors could be addressed. The new way would help reverse decisions and switch to a better solution in the middle of a project, without costing the project a limb.

Protean focuses on this thought process. It aims to help built robust applications that are well-tested and easy to improve while not being a slave to any one technology.
