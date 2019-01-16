.. _philosophy-decision-delay:

Delaying Decisions
==================

Because Protean promotes clear separation of your code from the underlying infrastructure, you can delay taking decisions until the last possible moment. 

Let's explore this concept with a database as an example.

Start with the bare minimum
---------------------------

If your application deals with a domain with complex business logic, you would want to focus on getting the domain model and functionality right, instead of worrying about the database schema. If your domain is sufficiently complex, the schema emerges over time, as mutually exclusive business rules make their way into the application.

Protean allows you to start with the bare minimum requirement. Why start with a graph DB if Mysql is sufficient? Why start with NoSQL database at all if a simple dictionary does the job?

Your application codebase remains the same and untouched, and the underlying implementation can be switched in a configuration file when you are ready.

Enhance as necessary
--------------------

When your project does reach sufficiently complex data model structure, and you see yourself doing things that are ideally done by a database (like complex joins), or you need to get to the next level in dataset size, you can change the application database to the one which fits the purpose.

Changing a database usually translates to a thorough testing exercise of the application. That's why we recommend covering up 100% of your application logic with tests. Once done, you can write testing coroutines that use your new database and run all tests on it.

Switch if required
------------------

Discovering an initial choice of a project is wrong is not as uncommon as we think. In most web applications, switching to a different database, let alone a different **kind** of a database (think SQL to NoSQL, or RDBMS to Graph) usually translates to a complete rewrite of the application. 

With Protean, you switch to the new underlying database without worrying about affected functionality and run your tests for guaranteed behavior.

.. note:: You should not hold off database integration until the very end. You should do it in bits and pieces, preferably along with your sprints, which ensures performance issues don't creep into the product. Resolving performance issues with complex logic can be a difficult task if left to the end.
