"""A real, importable domain package for the behavioral-analysis substrate.

The element index resolves classes two ways — by walking the domain's package on
disk, and by resolving a registered element's ``__module__`` by name — and both
need a package that actually exists on disk and actually imports. Elements
defined inside a test function cannot exercise the package walk, and a package
written to ``tmp_path`` cannot exercise the name-resolution door with real
Protean elements.

``elements`` holds one element of every type whose methods carry a role tag;
``helpers`` holds a plain class in a module that registers nothing, which is
what proves the walk is whole-package rather than element-driven.
"""
