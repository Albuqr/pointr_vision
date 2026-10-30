"""The cross-camera matcher (R2a 05, seam B, ADR 0007, D-058): maps each camera's local tracks to
group track IDs by court-plane position and time, or by appearance where position cannot decide.

Pure: it receives data as arguments and reads no clock, camera or file, so it is tested on
synthetic tracks and replayed in group time. The group runner calls `update` from each camera's
processing thread with that camera's tracks at one frame; the matcher keeps every camera's latest
tracks and compares the new frame with them. Rules:

* A track gets a group ID. A local track not yet linked to another camera joins the nearest track
  of another camera whose latest update is within `max_offset_s` and whose court position is within
  `match_distance_m`, one to one, nearest pair first; the group's rows then say `link=position`.
* Two local tracks of one camera that are present together are never put in one group.
* A local track that is no longer reported keeps its group ID for `lost_s`. A new local track near
  where such a group was last seen (`match_distance_m` plus `max_speed_mps` times the gap) takes the
  group over: a return, or an occlusion, re-links instead of creating a new ID.
* A track with no court position (camera not calibrated, point not projectable) is never linked by
  position. Where one of two tracks has no court position, their appearance (clothing colour and box
  height, `appearance.py`, R2a 06, D-059) decides instead, within `appearance_max_distance` and
  `max_height_diff`; the group's rows then say `link=appearance`. Where both have one, position
  alone decides. Pixel position is never a cue. Position pairs are taken before appearance pairs,
  and the takeover of a lost group follows the same rule: how an occluded track re-links.
"""

import dataclasses
import math
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from services.edge.appearance import Appearance, colour_distance, height_diff
from services.edge.contract import UNSHARED

POSITION = "position"  # the link of a track the matcher put with another camera's track
APPEARANCE = "appearance"  # the same, by appearance, where a court position was missing

Court = tuple[float, float]  # court metres
Key = tuple[str, int]  # camera_id, local tracker ID


@dataclass(frozen=True)
class MatcherParams:
    """The thresholds, recorded in run.json group.params (DATA_CONTRACTS section 3). Starting
    values, not measured ones."""

    match_distance_m: float = 0.5
    max_offset_s: float = 0.25
    lost_s: float = 1.0  # set to the tracker's lost-track time
    max_speed_mps: float = 4.0
    appearance_max_distance: float = 0.3  # mean Bhattacharyya distance, upper and lower box
    max_height_diff: float = 0.4  # |a - b| / max(a, b) of the box heights


@dataclass(frozen=True)
class LocalTrack:
    """One camera's track in one frame."""

    local_id: int  # the camera's own tracker ID
    xy: Court | None  # box bottom-centre in court metres; None: no court position
    appearance: Appearance | None = None  # clothing colour and box height; None: none


@dataclass(frozen=True)
class GroupTrack:
    local_id: int
    group_id: int  # the written track_id: the same person has the same one in every camera
    link: str  # tracks.csv `link`: `position`, `appearance` or `unshared`


@runtime_checkable
class CrossCameraMatcher(Protocol):  # ARCHITECTURE section 4
    def update(
        self, camera_id: str, t_recv: float, tracks: Sequence[LocalTrack]
    ) -> list[GroupTrack]:
        """The camera's tracks in the frame received at t_recv (PC clock), group IDs in the same
        order. Called once per processed frame, also when there are no tracks."""
        ...

    def record_params(self) -> dict:
        """The parameters in force, for run.json group.params."""
        ...


@dataclass
class _Local:
    gid: int | None
    last_t: float


@dataclass
class _Group:
    link: str
    last_t: float
    last_xy: Court | None
    last_app: Appearance | None = None


def _clean(xy: Court | None) -> Court | None:
    return xy if xy is not None and all(math.isfinite(v) for v in xy) else None


def _cue(p: MatcherParams, track: LocalTrack, xy: Court | None, app: Appearance | None, slack=0.0):
    """How `track` would link to something last seen at `xy` looking like `app`: (rank,
    distance, link), position first; None when not close. Appearance only when a position is
    missing on either side."""
    if track.xy is not None and xy is not None:
        d = math.dist(track.xy, xy)
        return (0, d, POSITION) if d <= p.match_distance_m + slack else None
    if track.appearance is not None and app is not None:
        d = colour_distance(track.appearance, app)
        if d <= p.appearance_max_distance and (
            height_diff(track.appearance, app) <= p.max_height_diff
        ):
            return (1, d, APPEARANCE)
    return None


class CourtMatcher:
    """CrossCameraMatcher by court position. `latency_s`: each camera's measured latency, subtracted
    from its receive time to get group time (0 for a camera without one, ADR 0002)."""

    def __init__(
        self, params: MatcherParams | None = None, latency_s: Mapping[str, float] | None = None
    ):
        self._p = params or MatcherParams()
        self._latency = dict(latency_s or {})
        self._lock = threading.Lock()  # every camera's processing thread calls update
        self._locals: dict[Key, _Local] = {}
        self._groups: dict[int, _Group] = {}
        self._latest: dict[str, tuple[float, dict[int, LocalTrack]]] = {}  # camera: t, tracks
        self._next_gid = 1

    def record_params(self) -> dict:
        """The parameters in force, for run.json group.params."""
        return {**dataclasses.asdict(self._p), "latency_s": dict(self._latency)}

    def update(
        self, camera_id: str, t_recv: float, tracks: Sequence[LocalTrack]
    ) -> list[GroupTrack]:
        with self._lock:
            t = t_recv - self._latency.get(camera_id, 0.0)
            self._expire(t)
            self._latest[camera_id] = (
                t, {tr.local_id: dataclasses.replace(tr, xy=_clean(tr.xy)) for tr in tracks}
            )  # fmt: skip
            keys = [(camera_id, tr.local_id) for tr in tracks]
            for key in keys:
                self._locals.setdefault(key, _Local(None, t)).last_t = t
            self._link_live(camera_id, t, keys)
            self._take_over_lost(t, keys)
            for key in keys:
                if self._locals[key].gid is None:
                    self._locals[key].gid = self._new_group()
            out = []
            for tr, key in zip(tracks, keys, strict=True):
                gid = self._locals[key].gid
                group = self._groups[gid]
                if (xy := _clean(tr.xy)) is not None:
                    group.last_t, group.last_xy = t, xy
                if tr.appearance is not None:
                    group.last_app = tr.appearance
                out.append(GroupTrack(tr.local_id, gid, group.link))
            return out

    # -- state -----------------------------------------------------------------------------

    def _new_group(self) -> int:
        gid, self._next_gid = self._next_gid, self._next_gid + 1
        self._groups[gid] = _Group(UNSHARED, 0.0, None)
        return gid

    def _expire(self, t: float) -> None:
        for key in [k for k, v in self._locals.items() if t - v.last_t > self._p.lost_s]:
            del self._locals[key]
        used = {v.gid for v in self._locals.values()}
        for gid in [g for g in self._groups if g not in used]:
            del self._groups[gid]

    def _members(self, gid: int) -> list[Key]:
        return [k for k, v in self._locals.items() if v.gid == gid]

    def _present(self, key: Key, t: float) -> bool:
        """In its camera's latest update, which is at most max_offset_s from t."""
        latest = self._latest.get(key[0])
        return (
            latest is not None
            and abs(t - latest[0]) <= self._p.max_offset_s
            and key[1] in latest[1]
        )

    def _compatible(self, a: list[Key], b: list[Key], t: float) -> bool:
        """No camera would have two present tracks in the joined group."""
        cameras = [k[0] for k in a + b if self._present(k, t)]
        return len(cameras) == len(set(cameras))

    def _join(self, keep: int, drop: int | None, key: Key, link: str | None = None) -> None:
        """Put `key` (and every track of group `drop`) into group `keep`."""
        self._locals[key].gid = keep
        if drop is not None and drop != keep:
            for member in self._members(drop):
                self._locals[member].gid = keep
            if self._groups[drop].last_t > self._groups[keep].last_t:  # the later sighting wins
                self._groups[keep].last_t = self._groups[drop].last_t
                self._groups[keep].last_xy = self._groups[drop].last_xy
            self._groups[keep].last_app = self._groups[keep].last_app or self._groups[drop].last_app
            del self._groups[drop]
        if link:
            self._groups[keep].link = link

    # -- matching --------------------------------------------------------------------------

    def _linked(self, gid: int | None) -> bool:
        return gid is not None and len({k[0] for k in self._members(gid)}) > 1

    def _link_live(self, camera_id: str, t: float, keys: list[Key]) -> None:
        """Tracks of this camera not yet linked to another camera, against the other cameras'
        current tracks."""
        p = self._p
        mine = self._latest[camera_id][1]
        pairs = []
        for key in keys:
            if self._linked(self._locals[key].gid):
                continue
            for cam, (t_cam, tracks) in self._latest.items():
                if cam == camera_id or abs(t - t_cam) > p.max_offset_s:
                    continue
                for lid, other in tracks.items():
                    if (cam, lid) not in self._locals:
                        continue
                    if cue := _cue(p, mine[key[1]], other.xy, other.appearance):
                        pairs.append((cue[0], cue[1], key, (cam, lid), cue[2]))
        for _, _, key, other, link in sorted(pairs):
            mine_gid, other_gid = self._locals[key].gid, self._locals[other].gid
            if self._linked(mine_gid) or mine_gid == other_gid:
                continue
            a = self._members(mine_gid) if mine_gid is not None else [key]
            if not self._compatible(a, self._members(other_gid), t):
                continue
            keep = other_gid
            if mine_gid is not None and not self._linked(other_gid):
                keep = min(mine_gid, other_gid)
            self._join(keep, mine_gid if mine_gid != keep else other_gid, key, link)

    def _take_over_lost(self, t: float, keys: list[Key]) -> None:
        """New local tracks near where a group with no present track was last seen, or (with no
        position on either side) looking like it."""
        p = self._p
        pairs = []
        for key in keys:
            track = self._latest[key[0]][1][key[1]]
            if self._locals[key].gid is not None:
                continue
            for gid, group in self._groups.items():
                if any(self._present(k, t) for k in self._members(gid)):
                    continue
                slack = p.max_speed_mps * max(t - group.last_t, 0.0)
                if cue := _cue(p, track, group.last_xy, group.last_app, slack):
                    pairs.append((cue[0], cue[1], key, gid, cue[2]))
        for _, _, key, gid, link in sorted(pairs):
            if self._locals[key].gid is None and not any(
                self._present(k, t) for k in self._members(gid)
            ):
                self._join(gid, None, key)
                if self._linked(gid) and self._groups[gid].link == UNSHARED:  # now two cameras
                    self._groups[gid].link = link
