.. _philosophy-dependency-rule:

Dependency Rule
===============

.. figure:: CleanArchitecture.jpg
   :alt: Clean Architecture

The overriding rule that makes this architecture work is The Dependency Rule. This rule says that source code dependencies can only point inwards. Nothing in an inner circle can know anything at all about something in an outer circle. In particular, the name of something declared in an outer circle must not be mentioned by the code in the an inner circle. That includes, functions, classes. variables, or any other named software entity.

By the same token, data formats used in an outer circle should not be used by an inner circle, especially if those formats are generate by a framework in an outer circle. We don’t want anything in an outer circle to impact the inner circles.

While projects start off in the right way in this direction, they usually fall down one of these traps:

* **Cross Imports**: If the business logic code is not housed in a separate repository than the API code, developers tend to start cross-pollinating the project over a period of time. It's just so much easier to import an existing class and get on with the functionality rather than think about keeping the interfaces clean.
* **Shared Data Entities**: The API layer will usually use the same data entity that is used to persist data into a database. Any change done to the database model gets automatically reflected in the API response, resulting in tight coupling.
* **Scattered Database Queries**: Over a period of time, projects tend to accumulate specialized queries for specific functionality, due to performance requirements or complexity in the data model. These scripts tend to get scattered in different files throughout the project over time, making a database switch close to impossible.
* **UI influenced Business Logic**: It is so tempting to just look at the UI screen requirements and model the data schemas to fulfill the request/response requirements. This creates a tight-coupling in the system all the way upto UI, resulting in any UI change having a rippling effect throughout the system.
