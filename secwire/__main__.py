"""`python -m secwire` — the same entry point as the installed `secwire` script."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
