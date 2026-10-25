# Saga lifecycle: start, intermediate, end

A saga has three kinds of handler, set by parameters on `@handle`. The SKILL.md,
steps 3 to 5, shows one handler of each kind.

## Start

A start handler opens the saga. Mark it `start=True`. When no instance exists yet
for that correlation value it creates one; when an open instance already exists
it loads that instance and runs on it. Once an instance is complete it is
skipped, so a repeated start event does not reopen a closed saga.

A saga needs at least one start handler, and it can have more than one: mark
every event that can begin the flow `start=True`, and whichever arrives first
creates the instance.

## Intermediate

An intermediate handler advances the flow: it updates the saga's state and
issues the command for the next step. It does not open or close the saga, so it
carries only `correlate`.

## End

A terminal handler closes the saga. Mark it `end=True`. After it runs, the
framework marks the instance complete, and any later event for that correlation
value is skipped.

A saga usually has more than one terminal handler: one for the success path and
one for each failure path.

## PROCESS_MANAGER_UNCLOSED

`check` reports `PROCESS_MANAGER_UNCLOSED` when a process manager has handlers
but none is marked `end=True`. The SKILL.md's anti-pattern section shows the
flagged asset and the fix.
