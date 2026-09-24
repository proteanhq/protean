# Verify your work with check

After you change a domain, run Protean's static check against it and resolve
everything it reports before you treat the work as done.

1. From the project root, run `protean check --domain=<your_domain>`. It loads
   the domain, validates it, and prints a diagnostic for each problem it finds.
   Most diagnostics carry a code.
2. If you are working through the MCP server instead, call the `check` tool on
   the changed domain. It returns the same full report. The `validate` tool is
   the narrower go/no-go answer: it tells you whether the domain is valid and
   lists its errors, but it does not carry the warning and info diagnostics, so
   use `check` when you need to read and resolve every finding.
3. Read each diagnostic, fix the cause in the domain code, and run the check
   again. Repeat until it reports nothing.

A change is not finished while `check` still reports a problem the change
introduced.
