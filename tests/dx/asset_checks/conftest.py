"""Keep the main suite from collecting these files.

Each file here runs in a child interpreter through
``tests.support.project_tests.run_tests_in``, so the example domains it loads
stay out of the test process.
"""

collect_ignore_glob = ["*.py"]
