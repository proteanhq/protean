.. _philosophy-core:

The Heart of Protean
====================

Much of what follows has been outlined in |uncle-bob-article|, but I will reiterate the core philosophy for everyone's benefit.

.. |uncle-bob-article| raw:: html

    <a href="http://blog.cleancoder.com/uncle-bob/2012/08/13/the-clean-architecture.html" target="_blank">Uncle Bob's article</a>

Clean Architecture as an idea is not new. There have been similar architectures outlined by various people like, Hexagonal Architecture, Onion Architecture, Screaming Architecture, and
Lean Architecture.

Though these architectures all vary somewhat in their details, they are very similar. They all have the same objective, which is the separation of concerns. They all achieve this separation by dividing the software into layers. Each has at least one layer for business rules, and another for interfaces.

An application built with Clean Architecture system would typically be:

* **Independent of Frameworks**: Application does not depend on the existence of some library of feature laden software. This allows the application to use such frameworks as tools, rather than having to shoe-horn the functionality into their limited constraints.
* **Testable**: The Application's business rules can be tested without the UI, Database, Web Server, or any other external element, making it faster, dependable and resitant to external changes
* **Independent of UI**: The UI of the application (or UIs, if multiple channels like Mobiles are involved) can change easily, without needing any changes to the rest of the system. A user should be able to use a console UI, in need be, without changing the business rules.
* **Independent of Database**: The application's business rules are not bound to the database. You can swap out one SQL database for another, or even switch to a NoSQL DB like Mongo, BigTable, CouchDB or Elasticsearch!
* **Independent of any external agency**: The application is basically agnostic to the outside world. The business rules simply don’t know anything at all about what it's like out there.

By being independent, an application allows developers to delay taking long-term decisions until the last possible moment.

What is a long-term decision? Anything that needs considerable time and effort to change, like the choice of a database or a web framework, or even the data format of messages between the backend and the UI, is considered a long-term decision. And what does a last possible moment look like? Any time frame beyond which not making a decision results in diminishing returns or declining productivity. As they say, sometime's a bad decision is much better than no decision at all. 

But the real beauty of a Clean Architecture compliant application would be that even after you have taken long-term decisions at the last possible moment, you can still go back to the blackboard and start anew, without spending a ton of time and effort. That's where interface definitions play a critical role. As long as your components adhere to the contract published by the application, you can switch between them freely and often, on the fly.

Protean is an application framework geared to get you on board the Clean Architecture wagon from day one. It was built based on learning and feedback while building applications for realworld clients. Unknown requirements, changing technology landscape, improved API communication and ever tighter deadlines pushed us to wonder if there was a way to build an application where all these factors could be addressed. Where we could actually go back on a decison and switch to a better solution in the middle of a project, without costing the project a tooth or a limb.
