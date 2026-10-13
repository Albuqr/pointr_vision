"""Compatibility CLI for the importable multi-camera launcher."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.edge import launcher_impl as _impl  # noqa: E402


def __getattr__(name):
    return getattr(_impl, name)


def main(argv=None):
    return _impl.main(argv)


if __name__ == "__main__":
    sys.exit(main())
