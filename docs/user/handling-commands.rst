=================
Handling Commands
=================

Commands are concepts from the CQRS design pattern.

Commands can be handled synchronously or asynchronously.

When handled synchronously, commands return a value to the caller. This can be useful when you want to immediately
commit a transaction when executing a request and return committed data.

When handled asynchronously, commands are verified to not violate invariants and then accepted to be processed later.
This pattern is closer in behavior to what is recommended generally in CQRS. But this may not be a viable option in
all systems or all use cases within a system.

Protean supports all three modes of command handling: Synchronous, Asynchronous, and a combination of both.

By default, command handling in Protean is Asynchronous.

Command handlers verify that the command does not violate invariants, and then raise an Event. The event is then
consumed by an event handler whose task is to update the data store. Optionally, the data can be updated in the
command handler before raising the event. But this is not good design if following EventSourcing principles.

Questions:
Should commands be verified to not violate invariants?
Are all DB changes to be performed through Events?
