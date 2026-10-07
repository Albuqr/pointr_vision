from pathlib import Path

import pytest

from fixtures.make_clips import make_clips


@pytest.fixture(scope="session")
def clips(tmp_path_factory) -> dict[str, Path]:
    """Synthetic clips generated once per test session: moving, black, frozen."""
    return make_clips(tmp_path_factory.mktemp("clips"))
