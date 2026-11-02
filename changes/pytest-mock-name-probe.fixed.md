Importing `current_domain` or `g` into a test module no longer prints a "Working outside of domain context" warning during collection on pytest 9.2, which reads `_mock_name` on every imported name.
