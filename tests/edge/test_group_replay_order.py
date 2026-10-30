"""The order of a group replay (R2a 08, D-059): the cameras' frames reach the matcher one at a time
in group time, whatever pace each camera's processing thread has."""

import random
import threading
import time

from services.edge.replay.order import GroupTimeOrder


def run_cameras(order, frames: dict[str, int], finish_after: dict[str, int] | None = None):
    """One thread per camera calling turn() for its frames, at a random pace; returns what entered
    the turn, in the order it did, and checks nobody was inside it at the same time."""
    entered, inside = [], []
    lock = threading.Lock()
    finish_after = finish_after or {}

    def camera(cid, rng):
        for seq in range(finish_after.get(cid, frames[cid])):
            time.sleep(rng.random() * 0.003)
            with order.turn(cid, seq) as t:
                with lock:
                    inside.append(cid)
                    assert len(inside) == 1, "two cameras in the matcher at once"
                    entered.append((t, cid, seq))
                time.sleep(rng.random() * 0.001)
                with lock:
                    inside.remove(cid)
        order.finish(cid)

    threads = [
        threading.Thread(target=camera, args=(cid, random.Random(i)))
        for i, cid in enumerate(frames)
    ]
    for th in threads:
        th.start()
    for th in threads:
        th.join(10)
    assert not any(th.is_alive() for th in threads), "a camera is stuck"
    return entered


def test_frames_enter_in_group_time_order_with_each_frames_group_time():
    order = GroupTimeOrder({"cam1": lambda s: 0.1 * s, "cam2": lambda s: 0.05 + 0.15 * s})
    entered = run_cameras(order, {"cam1": 30, "cam2": 20})
    assert [(t, c) for t, c, _ in entered] == sorted((t, c) for t, c, _ in entered)
    assert len(entered) == 50
    assert all(t == (0.1 * s if c == "cam1" else 0.05 + 0.15 * s) for t, c, s in entered)


def test_equal_times_go_in_the_cameras_order():
    order = GroupTimeOrder({"cam2": lambda s: float(s), "cam1": lambda s: float(s)})
    entered = run_cameras(order, {"cam2": 10, "cam1": 10})
    assert [c for _, c, _ in entered] == ["cam2", "cam1"] * 10  # as given, not alphabetical


def test_a_camera_whose_frames_end_early_does_not_hold_the_others():
    order = GroupTimeOrder({"cam1": lambda s: float(s), "cam2": lambda s: float(s)})
    entered = run_cameras(order, {"cam1": 20, "cam2": 20}, finish_after={"cam2": 3})
    assert sum(c == "cam1" for _, c, _ in entered) == 20


def test_a_skipped_frame_does_not_hold_the_others():
    """A camera's next frame is the one it brings: a frame it never brings (not processed) is not
    waited for."""
    order = GroupTimeOrder({"cam1": lambda s: float(s), "cam2": lambda s: float(s)})
    seen = []

    def cam2():
        for seq in (0, 5, 6):
            with order.turn("cam2", seq):
                seen.append(("cam2", seq))
        order.finish("cam2")

    th = threading.Thread(target=cam2)
    th.start()
    for seq in range(8):
        with order.turn("cam1", seq):
            seen.append(("cam1", seq))
    order.finish("cam1")
    th.join(5)
    assert not th.is_alive()
    assert seen.index(("cam1", 4)) < seen.index(("cam2", 5)) < seen.index(("cam1", 6))


def test_close_lets_every_waiting_camera_through():
    order = GroupTimeOrder({"cam1": lambda s: float(s), "cam2": lambda s: float(s)})
    passed = threading.Event()

    def cam1():
        with order.turn("cam1", 5):  # waits for cam2's frames 0 to 5, which never come
            passed.set()

    th = threading.Thread(target=cam1)
    th.start()
    assert not passed.wait(0.2)
    order.close()  # a stop: nobody waits any more
    assert passed.wait(2)
    th.join(2)
