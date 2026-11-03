"""CLI entry for the multi-camera launcher: python scripts/run_cameras.py --help."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.edge.launcher import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
