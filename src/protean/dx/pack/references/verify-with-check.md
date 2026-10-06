# Verify your work with check

After you change a domain, run Protean's static check against it and resolve
the errors and warnings your change introduced before you treat the work as
done.

1. From the project root, run `protean check --domain=<your_domain> --level=warning`.
   It loads the domain, validates it, and prints a diagnostic for each error
   and warning it finds. Most diagnostics carry a code. `--level=warning` hides
   the info-level diagnostics. Many domains keep some of those on purpose, so
   they are not a reason to keep going.
2. If one module defines two domains, name the one to check after a colon:
   `protean check --domain=myapp.domain:billing --level=warning`. The part
   before the colon is the module and the part after it is the name of the
   `Domain` variable in that module.
3. If you are working through the MCP server instead, call the `check` tool on
   the changed domain. It returns the same full report. The `validate` tool is
   the narrower go/no-go answer: it tells you whether the domain is valid and
   lists its errors, but it does not carry the warning and info diagnostics, so
   use `check` when you need to read and resolve every finding.
4. Read each error and warning, fix the cause in the domain code, and run the
   check again.

Stop when `check --level=warning` reports no error or warning that your change
introduced. A domain may already carry warnings from before your change. Leave
those alone unless the task is to fix them. Run the check once before you start
if you need to tell the two apart.
