"""The cross-camera matcher (R2a 05, seam B, ADR 0007): court position and time, on synthetic
tracks. No frames, no detector, no clock: group time is what the test passes in."""

import pytest

from services.edge import contract
from services.edge.contract import UNSHARED
from services.edge.matcher import CourtMatcher, CrossCameraMatcher, LocalTrack, MatcherParams


def feed(m, camera_id, t, **tracks):
    """One camera's update at receive time t: track name `l7` is local ID 7; a value of None is
    a track with no court position. Returns {local_id: (group_id, link)}."""
    out = m.update(camera_id, t, [LocalTrack(int(name[1:]), xy) for name, xy in tracks.items()])
    return {g.local_id: (g.group_id, g.link) for g in out}


def test_the_matcher_satisfies_its_protocol():
    assert isinstance(CourtMatcher(), CrossCameraMatcher)


def test_a_person_at_the_same_court_point_in_both_cameras_gets_one_group_id():
    m = CourtMatcher()
    a = feed(m, "A", 0.0, l1=(5.0, 5.0))
    assert a[1][1] == UNSHARED  # nobody else has seen the person yet
    b = feed(m, "B", 0.02, l7=(5.1, 5.0))
    assert b[7] == (a[1][0], "position")
    assert feed(m, "A", 0.07, l1=(5.0, 5.0))[1] == (a[1][0], "position")


def test_people_further_apart_than_the_match_distance_stay_apart():
    m = CourtMatcher()
    a = feed(m, "A", 0.0, l1=(5.0, 5.0))
    b = feed(m, "B", 0.02, l7=(6.0, 5.0))
    assert a[1][0] != b[7][0] and b[7][1] == UNSHARED


def test_two_people_side_by_side_stay_apart_and_each_pairs_with_the_nearest():
    m = CourtMatcher()
    a = feed(m, "A", 0.0, l1=(5.0, 5.0), l2=(5.3, 5.0))  # closer than match_distance_m
    b = feed(m, "B", 0.02, l8=(5.3, 5.05), l7=(5.0, 5.05))
    assert a[1][0] != a[2][0]
    assert b[7][0] == a[1][0] and b[8][0] == a[2][0]


def test_two_local_tracks_of_one_camera_present_together_are_never_merged():
    m = CourtMatcher()
    a = feed(m, "A", 0.0, l1=(5.0, 5.0), l2=(5.1, 5.0))
    b = feed(m, "B", 0.02, l7=(5.05, 5.0))  # within reach of both
    assert a[1][0] != a[2][0]
    assert b[7][0] in (a[1][0], a[2][0])  # it joins one of them, not both
    # two tracks of B near one track of A: only one of them joins it
    m = CourtMatcher()
    a = feed(m, "A", 0.0, l1=(5.0, 5.0))
    b = feed(m, "B", 0.02, l7=(5.0, 5.0), l8=(5.1, 5.0))
    assert {b[7][0], b[8][0]} != {a[1][0]} and b[7][0] != b[8][0]


def test_a_track_lost_and_back_within_the_lost_time_keeps_its_group_id():
    m = CourtMatcher(MatcherParams(lost_s=1.0))
    g = feed(m, "A", 0.0, l1=(5.0, 5.0))[1][0]
    feed(m, "A", 0.5)  # not reported: lost
    assert feed(m, "A", 0.9, l1=(5.3, 5.0))[1][0] == g  # the same local ID returns
    feed(m, "A", 1.0)
    # the tracker gave the person a new local ID, a little way on
    assert feed(m, "A", 1.4, l9=(5.8, 5.0))[9][0] == g


def test_a_track_lost_for_longer_than_the_lost_time_gets_a_new_group_id():
    m = CourtMatcher(MatcherParams(lost_s=1.0))
    g = feed(m, "A", 0.0, l1=(5.0, 5.0))[1][0]
    feed(m, "A", 0.5)
    assert feed(m, "A", 2.0, l9=(5.0, 5.0))[9][0] != g
    assert feed(m, "A", 2.5, l1=(5.0, 5.0))[1][0] != g  # the local ID was forgotten too


def test_a_lost_track_is_not_taken_over_by_someone_far_from_where_it_was_lost():
    m = CourtMatcher(MatcherParams(lost_s=1.0, match_distance_m=0.5, max_speed_mps=4.0))
    g = feed(m, "A", 0.0, l1=(5.0, 5.0))[1][0]
    feed(m, "A", 0.2)
    assert feed(m, "A", 0.5, l9=(12.0, 5.0))[9][0] != g  # 7 m in 0.5 s


def test_a_new_track_does_not_take_over_a_group_that_is_still_present():
    m = CourtMatcher()
    g = feed(m, "A", 0.0, l1=(5.0, 5.0))[1][0]
    out = feed(m, "A", 0.1, l1=(5.0, 5.0), l2=(5.1, 5.0))  # two people, one just arrived
    assert out[1][0] == g and out[2][0] != g


def test_a_camera_that_comes_back_with_new_local_ids_relinks_by_position():
    m = CourtMatcher(MatcherParams(lost_s=1.0))
    g = feed(m, "A", 0.0, l1=(5.0, 5.0))[1][0]
    assert feed(m, "B", 0.02, l7=(5.0, 5.0))[7][0] == g
    for i in range(1, 32):  # B's stream drops at 0.02; A goes on, past lost_s for B's local ID 7
        a = feed(m, "A", i / 10, l1=(5.0, 5.0))
    b = feed(m, "B", 3.12, l31=(5.1, 5.0))
    assert b[31] == (g, "position") and a[1][0] == g


def test_a_track_with_no_court_position_is_never_linked():
    m = CourtMatcher()
    a = feed(m, "A", 0.0, l1=None)
    b = feed(m, "B", 0.02, l7=(5.0, 5.0))
    assert a[1][0] != b[7][0] and {a[1][1], b[7][1]} == {UNSHARED}
    # also when the uncalibrated camera is the one that reports second
    c = feed(m, "A", 0.05, l1=None, l2=None)
    assert {v[0] for v in c.values()}.isdisjoint({b[7][0]})


def test_a_camera_that_stopped_reporting_is_not_matched():
    m = CourtMatcher(MatcherParams(max_offset_s=0.25))
    a = feed(m, "A", 0.0, l1=(5.0, 5.0))
    b = feed(m, "B", 3.0, l7=(5.0, 5.0))  # A's last update is 3 s old
    assert b[7][0] != a[1][0]


def test_cameras_are_aligned_on_the_pc_clock_minus_their_latency():
    # B's frame arrived at 10.6 on the PC clock but was captured 0.5 s earlier
    params = MatcherParams(max_offset_s=0.25, lost_s=0.3)
    m = CourtMatcher(params, latency_s={"B": 0.5})
    a = feed(m, "A", 10.0, l1=(5.0, 5.0))
    assert feed(m, "B", 10.6, l7=(5.0, 5.0))[7] == (a[1][0], "position")
    m = CourtMatcher(params)  # no latency measured: 0.6 s apart is too far
    a = feed(m, "A", 10.0, l1=(5.0, 5.0))
    assert feed(m, "B", 10.6, l7=(5.0, 5.0))[7][0] != a[1][0]


def test_thresholds_come_from_the_parameters():
    tight = CourtMatcher(MatcherParams(match_distance_m=0.1))
    feed(tight, "A", 0.0, l1=(5.0, 5.0))
    assert feed(tight, "B", 0.02, l7=(5.3, 5.0))[7][1] == UNSHARED
    loose = CourtMatcher(MatcherParams(match_distance_m=1.0))
    feed(loose, "A", 0.0, l1=(5.0, 5.0))
    assert feed(loose, "B", 0.02, l7=(5.6, 5.0))[7][1] == "position"


def test_params_are_the_names_run_json_records():
    p = CourtMatcher(MatcherParams(lost_s=2.0), latency_s={"B": 0.08}).record_params()
    assert tuple(p) == contract.MATCHER_PARAMS
    assert p["lost_s"] == 2.0 and p["latency_s"] == {"B": 0.08}


def test_group_ids_are_unique_and_follow_the_input_order():
    m = CourtMatcher()
    out = m.update("A", 0.0, [LocalTrack(5, (1.0, 1.0)), LocalTrack(3, (9.0, 9.0))])
    assert [g.local_id for g in out] == [5, 3]
    assert len({g.group_id for g in out}) == 2


def test_the_same_inputs_give_the_same_ids():
    def run():
        m = CourtMatcher()
        seen = []
        for t in (0.0, 0.1, 0.2):
            seen.append(feed(m, "A", t, l1=(5.0, 5.0), l2=(8.0, 3.0)))
            seen.append(feed(m, "B", t + 0.02, l4=(8.0, 3.1), l3=(5.1, 5.0)))
        return seen

    assert run() == run()


@pytest.mark.parametrize("bad", [(float("nan"), 1.0), (float("inf"), 1.0)])
def test_a_position_that_is_not_finite_counts_as_no_position(bad):
    m = CourtMatcher()
    a = feed(m, "A", 0.0, l1=(5.0, 5.0))
    assert feed(m, "B", 0.02, l7=bad)[7][0] != a[1][0]
