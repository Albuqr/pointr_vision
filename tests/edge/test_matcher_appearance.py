"""The appearance fallback (R2a 06, seam B, ADR 0007, D-059): clothing colour and box height, on
synthetic people drawn as two coloured blocks. No detector, no clock, no camera."""

import dataclasses

import numpy as np
import pytest

from services.edge import contract
from services.edge.appearance import Appearance, colour_distance, describe, height_diff
from services.edge.contract import UNSHARED
from services.edge.matcher import CourtMatcher, LocalTrack, MatcherParams

RED, BLUE, GREEN = (0, 0, 255), (255, 0, 0), (0, 160, 0)  # BGR
WHITE, BLACK = (255, 255, 255), (0, 0, 0)


def look(shirt, shorts, height=0.5, seed=0):
    """A person in `shirt` over `shorts` whose box is `height` of a 400 px frame, with a little
    sensor noise so two looks at one kit are close but not identical."""
    img = np.zeros((400, 100, 3), np.float32)
    h = int(400 * height)
    img[: h // 2], img[h // 2 : h] = shirt, shorts
    noise = np.random.default_rng(seed).normal(0, 8, img.shape)
    return describe(np.clip(img + noise, 0, 255).astype(np.uint8), (0, 0, 100, h))


def see(m, camera_id, t, **tracks):
    """One camera's update: `l7=(xy, appearance)` is local ID 7. {local_id: (group_id, link)}."""
    out = m.update(camera_id, t, [LocalTrack(int(n[1:]), xy, a) for n, (xy, a) in tracks.items()])
    return {g.local_id: (g.group_id, g.link) for g in out}


# -- the descriptor ------------------------------------------------------------------------


def test_one_kit_seen_twice_is_close_and_different_kits_are_far():
    assert colour_distance(look(RED, BLUE), look(RED, BLUE, seed=1)) < 0.05
    assert colour_distance(look(RED, BLUE), look(GREEN, WHITE)) > 0.9
    assert colour_distance(look(WHITE, WHITE), look(BLACK, BLACK)) > 0.9  # value counts
    assert colour_distance(look(RED, BLUE), look(BLUE, RED)) > 0.9  # upper and lower apart


def test_the_height_is_a_fraction_of_the_frame():
    assert look(RED, BLUE, 0.5).height == 0.5
    assert height_diff(look(RED, BLUE, 0.5), look(RED, BLUE, 0.2)) == pytest.approx(0.6)


@pytest.mark.parametrize(
    "box", [(200, 20, 300, 80), (10, 10, 10, 50), (10, 50, 40, 50), (float("nan"), 0, 5, 5)]
)
def test_a_box_with_nothing_to_describe_has_no_descriptor(box):
    assert describe(np.zeros((100, 100, 3), np.uint8), box) is None


def test_a_box_partly_outside_the_frame_is_described_from_the_part_inside():
    a = describe(np.zeros((100, 100, 3), np.uint8), (-20, 10, 60, 160))
    assert a is not None and a.height == 1.5


def test_the_descriptor_holds_no_pixel_position():
    """Nothing in what the matcher receives says where the box is in the image."""
    assert [f.name for f in dataclasses.fields(LocalTrack)] == ["local_id", "xy", "appearance"]
    assert [f.name for f in dataclasses.fields(Appearance)] == ["upper", "lower", "height"]


# -- the matcher ---------------------------------------------------------------------------


def test_an_uncalibrated_camera_links_by_a_close_appearance():
    m = CourtMatcher()
    a = see(m, "A", 0.0, l1=((5.0, 5.0), look(RED, BLUE)))
    b = see(m, "B", 0.02, l7=(None, look(RED, BLUE, seed=1)))  # no court position
    assert b[7] == (a[1][0], "appearance")
    assert see(m, "A", 0.07, l1=((5.0, 5.0), look(RED, BLUE)))[1] == (a[1][0], "appearance")


def test_two_uncalibrated_cameras_link_by_appearance_and_keep_two_people_apart():
    m = CourtMatcher()
    a = see(m, "A", 0.0, l1=(None, look(RED, BLUE)), l2=(None, look(GREEN, WHITE)))
    b = see(m, "B", 0.02, l8=(None, look(GREEN, WHITE, seed=1)), l7=(None, look(RED, BLUE, seed=1)))
    assert b[7] == (a[1][0], "appearance") and b[8] == (a[2][0], "appearance")


@pytest.mark.parametrize(
    "first,second",
    [
        (look(RED, BLUE), look(GREEN, WHITE)),
        (look(WHITE, WHITE), look(BLACK, BLACK)),
        (look(RED, BLUE, 0.5), look(RED, BLUE, 0.2, seed=1)),  # same kit, much shorter box
    ],
    ids=["colour", "black-white", "height"],
)
def test_a_distant_appearance_does_not_link(first, second):
    m = CourtMatcher()
    a = see(m, "A", 0.0, l1=(None, first))
    b = see(m, "B", 0.02, l7=(None, second))
    assert b[7][0] != a[1][0] and {a[1][1], b[7][1]} == {UNSHARED}


def test_no_link_without_a_court_position_or_an_appearance():
    m = CourtMatcher()
    a = see(m, "A", 0.0, l1=(None, None))
    b = see(m, "B", 0.02, l7=(None, look(RED, BLUE)))
    assert b[7][0] != a[1][0] and b[7][1] == UNSHARED


def test_appearance_never_overrides_the_court_position():
    m = CourtMatcher()
    a = see(m, "A", 0.0, l1=((5.0, 5.0), look(RED, BLUE)))
    b = see(m, "B", 0.02, l7=((9.0, 5.0), look(RED, BLUE, seed=1)))  # same kit, 4 m apart
    assert b[7][0] != a[1][0] and b[7][1] == UNSHARED


def test_a_court_position_match_is_taken_before_an_appearance_match():
    m = CourtMatcher()
    a = see(m, "A", 0.0, l1=((5.0, 5.0), look(GREEN, WHITE)), l2=(None, look(RED, BLUE)))
    b = see(m, "B", 0.02, l7=((5.1, 5.0), look(RED, BLUE, seed=1)))  # near l1, looks like l2
    assert b[7] == (a[1][0], "position")


def test_two_local_tracks_of_one_camera_in_one_kit_are_never_merged():
    m = CourtMatcher()
    a = see(m, "A", 0.0, l1=(None, look(RED, BLUE)), l2=(None, look(RED, BLUE, seed=1)))
    b = see(m, "B", 0.02, l7=(None, look(RED, BLUE, seed=2)))
    assert a[1][0] != a[2][0] and b[7][0] in (a[1][0], a[2][0])


def test_a_track_hidden_behind_another_relinks_by_appearance_within_the_lost_time():
    m = CourtMatcher(MatcherParams(lost_s=1.0))
    out = see(m, "A", 0.0, l1=(None, look(RED, BLUE)), l2=(None, look(GREEN, WHITE)))
    see(m, "A", 0.3, l2=(None, look(GREEN, WHITE)))  # l1 walks behind l2
    back = see(m, "A", 0.6, l2=(None, look(GREEN, WHITE)), l3=(None, look(RED, BLUE, seed=1)))
    assert back[3] == (out[1][0], UNSHARED)  # the tracker restarted it as l3; one camera only
    assert back[2][0] == out[2][0]


def test_a_track_hidden_for_longer_than_the_lost_time_gets_a_new_id():
    m = CourtMatcher(MatcherParams(lost_s=1.0))
    g = see(m, "A", 0.0, l1=(None, look(RED, BLUE)))[1][0]
    see(m, "A", 0.5)
    assert see(m, "A", 2.0, l3=(None, look(RED, BLUE, seed=1)))[3][0] != g


def test_a_hidden_track_is_not_taken_over_by_someone_who_looks_different():
    m = CourtMatcher(MatcherParams(lost_s=1.0))
    g = see(m, "A", 0.0, l1=(None, look(RED, BLUE)))[1][0]
    see(m, "A", 0.3)
    assert see(m, "A", 0.6, l3=(None, look(GREEN, WHITE)))[3][0] != g


def test_the_appearance_thresholds_come_from_the_parameters():
    a, b = look(RED, BLUE), look((30, 30, 200), (200, 30, 30))  # another shade of the kit
    for params, link in (
        (MatcherParams(appearance_max_distance=0.1), UNSHARED),
        (MatcherParams(appearance_max_distance=0.5), "appearance"),
        (MatcherParams(appearance_max_distance=0.5, max_height_diff=0.0), "appearance"),
    ):
        m = CourtMatcher(params)
        see(m, "A", 0.0, l1=(None, a))
        assert see(m, "B", 0.02, l7=(None, b))[7][1] == link
    m = CourtMatcher(MatcherParams(max_height_diff=0.1))
    see(m, "A", 0.0, l1=(None, look(RED, BLUE, 0.5)))
    assert see(m, "B", 0.02, l7=(None, look(RED, BLUE, 0.4, seed=1)))[7][1] == UNSHARED


def test_params_record_the_appearance_thresholds():
    p = CourtMatcher(MatcherParams(appearance_max_distance=0.2)).record_params()
    assert tuple(p) == contract.MATCHER_PARAMS
    assert p["appearance_max_distance"] == 0.2 and p["max_height_diff"] == 0.4


def test_a_court_position_older_than_the_lost_time_does_not_take_over_a_group():
    """A group kept alive by an uncalibrated camera has an old court position: after the lost
    time the speed slack would cover the court, so that position no longer decides."""
    m = CourtMatcher(MatcherParams(lost_s=1.0, max_offset_s=5.0))
    g = see(m, "A", 0.0, l1=((5.0, 5.0), look(RED, BLUE)))[1][0]
    for i in range(1, 30):  # B (no position) keeps the group alive, A has lost the person
        assert see(m, "B", i / 10, l7=(None, look(RED, BLUE, seed=1)))[7][0] == g
    see(m, "B", 3.0)  # B loses the person too
    far = see(m, "A", 3.2, l9=((12.0, 5.0), look(GREEN, WHITE)))  # 7 m off, other kit
    assert far[9][0] != g


def test_a_takeover_by_appearance_from_a_new_camera_says_appearance():
    m = CourtMatcher(MatcherParams(lost_s=1.0, max_offset_s=0.25))
    a = see(m, "A", 0.0, l1=((5.0, 5.0), look(RED, BLUE)))
    see(m, "B", 0.02, l7=((5.0, 5.0), look(RED, BLUE, seed=1)))  # linked by position
    see(m, "A", 0.5)
    see(m, "B", 0.52)  # both lose the person
    c = see(m, "C", 0.7, l3=(None, look(RED, BLUE, seed=2)))  # a third, uncalibrated camera
    assert c[3] == (a[1][0], "appearance")
