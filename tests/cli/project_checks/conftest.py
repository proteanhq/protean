"""Keep the main suite from collecting these files.

Each file here runs in a child interpreter, inside a project that a test in the
parent folder builds, through ``tests.support.project_tests.run_tests_in``. Its
imports only resolve there.
"""

collect_ignore_glob = ["*.py"]
