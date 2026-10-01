# =============================================================================
# FILE:    farm/__main__.py
# PURPOSE: Lets you run the farm with `python -m farm ...`.
# =============================================================================

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
