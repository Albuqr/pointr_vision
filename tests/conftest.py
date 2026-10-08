import sys
from pathlib import Path

import pytest

from fixtures.make_clips import make_clips


@pytest.fixture(autouse=True)
def no_model_outside_slow_tests(request):
    """Default tests must not load RF-DETR: it imports torch and downloads the weights."""
    loaded_before = "rfdetr" in sys.modules
    yield
    if request.node.get_closest_marker("slow") is None and not loaded_before:
        assert "rfdetr" not in sys.modules, "a default test imported rfdetr; mark it slow"


@pytest.fixture(scope="session")
def clips(tmp_path_factory) -> dict[str, Path]:
    """Synthetic clips generated once per test session: moving, black, frozen."""
    return make_clips(tmp_path_factory.mktemp("clips"))
