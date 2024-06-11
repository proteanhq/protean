# Domain object

Constructing the object graph is a two-step procedure. First, you initialize a
domain object at a reasonable starting point of the application.

## Initialize the domain object

```py hl_lines="3"
{! docs_src/guides/composing-a-domain/001.py !}
```

## Parameters

### **`root_path`**

The mandatory `root_path` parameter is the directory containing the domain's
elements.

Typically, this is the folder containing the file initializing the domain
object. Protean uses this path to traverse the directory structure
and [auto-discover domain elements](#auto-discover-domain-elements) when the
domain is [initialized](#initialize-the-domain).

In the example below, the domain is defined in `my_domain.py`. Domain elements
are nested within the `src` folder, directly or in their own folders. 

```shell
my_project
├── src
│   └── my_domain.py
│   └── authentication
│      └── user_aggregate.py
│      └── account_aggregate.py
├── pyproject.toml
├── poetry.lock
```

<!-- FIXME Create a "domain structuring" guide -->
Review the guide on structuring your domain for more information.

### **`name`**

The constructor also accepts an optional domain name to uniquely identify the
domain in the application ecosystem.

!!!note
    When not specified, the name is initialized to the name of the module
    defining the domain. Typically, this is the name of the file in which
    the domain is defined, without the `.py` extension.

### **`identity_function`**

The function to use to generate unique identity values.

```py hl_lines="7-9 11 14"
{! docs_src/guides/composing-a-domain/022.py !}
```
