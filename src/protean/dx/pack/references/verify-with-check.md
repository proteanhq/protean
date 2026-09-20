# Verify your work with check

After you change a domain, run Protean's static check against it and resolve
everything it reports before you treat the work as done.

1. From the project root, run `protean check --domain=<your_domain>`. It loads
   the domain, validates it, and prints a diagnostic for each problem it finds.
   Most diagnostics carry a code.
2. If you are working through the MCP server instead, call the `validate` (or
   `check`) tool on the changed domain. It returns the same diagnostics.
3. Read each diagnostic, fix the cause in the domain code, and run the check
   again. Repeat until it reports nothing.

A change is not finished while `check` still reports a problem the change
introduced.
