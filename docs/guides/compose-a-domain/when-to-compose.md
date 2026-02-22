# When to compose

!!! abstract "Applies to: DDD · CQRS · Event Sourcing"


The `Domain` class in Protean acts as a composition root. It manages external
dependencies and injects them into objects during application startup.

Your domain should be composed at the start of the application lifecycle. In 
simple console applications, the `main` method is a good entry point. In most
web applications that spin up their own runtime, we depend on the callbacks or 
hooks of the framework to compose the object graph, activate the composition
root, and inject dependencies into objects.

Accordingly, depending on the software stack you will ultimately use, you will decide when to activate the domain.

Below is an example of composing the domain with Flask as the API framework.
You would compose the domain along with the app object, and activate it (push
up the context) before processing a request.


```python hl_lines="29 33 35 38"
{! docs_src/guides/compose-a-domain/019.py !}
```
