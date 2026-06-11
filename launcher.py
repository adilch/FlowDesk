"""PyInstaller entry point (the packaged exe runs this; dev uses `uv run flowdesk`)."""

import sys

from flowdesk.ui.main import main

if __name__ == "__main__":
    sys.exit(main())
