"""Module execution entrypoint (`python3 -m ios_debloat`)."""
from __future__ import annotations

import sys

from ios_debloat.cli import main

if __name__ == "__main__":
    sys.exit(main())
