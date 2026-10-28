import sys
from pathlib import Path

import pytest

from fixtures import make_clips as clip_maker
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


@pytest.fixture(scope="session")
def long_clips(tmp_path_factory) -> list[Path]:
    """Two 30 s synthetic clips (they play in real time, so a stop lands mid-recording)."""
    folder = tmp_path_factory.mktemp("long")
    frames = [clip_maker.scene(i % 30) for i in range(30 * 15)]
    return [clip_maker.write_clip(folder / f"long{i}.mp4", frames) for i in (1, 2)]
