.. _introduction:

Introduction
============

In Short...
-----------

Protean allows your application to be:

* **Independent of Frameworks**: The philosophy is important, not the implementation. You don't necessarily depend on "Protean" library, as well. Protean is a just a lightweight collection of base classes and interfaces that will help you get on with your application development, faster.
* **Flexible**: Do gravity defying, brain-twisting, dangerous stunts like switching databases, writing into different databases at the same time, moving across to faster web frameworks etc. all this while not rewriting even one line of existing code.
* **Testable**: 100% coverage is not a mirage anymore.
* **Independent of Implementation Details** (like UI, Database, Cache, and Messaging Medium): You don't have to decide on your application stack on day one. And when you do decide, you can  change your mind again!

The Long Version
----------------

Would you buy a car if someone told you that you would have to replace the entire car if you tear a chair cushion?

Everywhere around us, we see examples of product architectures built for replaceability. Components work very well with each other yet are not tightly coupled. Each component adheres to a well-understood, well-published contract. So as long as the "contract" is fulfilled, a component can be replaced with its competitor's parts. You see this in Physical products like Cars, Laptops, Furniture, Kitchen Equipment and list goes on. Want to enter a market for rubber gaskets? Just look up the contract (dimensions, quality, durability), fulfill them in your product at the lowest cost possible, and you are on. Marketing that is necessary to get your product into the hands of the consumer is an entirely different story, but creating a new product is relatively simple.

Somehow this thought process has not been prevalent in the software industry. Yes, we do have a few excellent examples, but they are few and far in between. When one builds an application, all components are supposed to live their life out together, until they all die out. Forget about replacing a faulty component or switching to a better component.

Let's take another example. What if you wanted to change a specific piece of your software application. It could be because technology changes have made a task cheaper/simpler, a competitor of a component you use is offering better rates for the same functionality, or the component has not kept up with the times and is dying a slow painful death due to non-maintainability. As a developer, would you want to plug in the new component or would you want to spend some (considerable?) effort of time rewriting code to switch to the new component? More importantly, what happens the next time you decide to change the component again?

Clean architecture not only allows you to design applications with very low coupling and independent of technical implementation details (think databases and frameworks), it also makes applications easy to maintain and flexible to change. Plus applications become intrinsically testable. Think 100% coverage. Does that not sound like a dream?

Uncle Bob presents a solid case for Clean Architecture on his |bob_blog|. However, the idea itself is not new. The central focus of the philosophy is to ensure that the dependencies between components are correctly arranged and to ensure all implementation details adhere to a set of contracts (Think Interfaces, Plugins, Adapters.)

Protean attempts to mainstream this idea while ensuring that the entry bar for a development team just starting on their clean architecture journey is low. While it espouses the idea of a plugin-based architecture, it also supplies adapters out of the box for most popular technical implementations (Think Databases, Web Frameworks, Messaging Mediums, and Cache Providers). Protean does not attempt to replace any of these components; it just tries to make you avoid getting locked into them. If you ever want to switch a technical implementation into some other product, you are covered from day one.

.. |bob_blog| raw:: html

   <a href="http://blog.cleancoder.com/uncle-bob/2012/08/13/the-clean-architecture.html" target="_blank">blog</a>