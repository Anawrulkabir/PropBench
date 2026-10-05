"""Entry point: ``python -I -B -X utf8 -m propbench.worker``."""

import sys

from propbench.worker.server import main

sys.exit(main())
