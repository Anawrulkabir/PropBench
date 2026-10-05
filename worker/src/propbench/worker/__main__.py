"""Entry point: ``python -I -B -X utf8 -m propbench.worker``."""

import sys

from propbench.worker.server import main

# Guarded: validation workers started with the "spawn" method import this module as __mp_main__ and must not serve.
if __name__ == "__main__":
    sys.exit(main())
