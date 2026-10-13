"""Compatibility CLI for the importable multi-camera launcher."""

from services.edge import launcher_impl as _impl


def __getattr__(name):
    return getattr(_impl, name)


def main(argv=None):
    return _impl.main(argv)


if __name__ == "__main__":
    import sys

    sys.exit(main())
