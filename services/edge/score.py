"""Score a hand-labelled session against its logs (FR-013, AC-013.1).

    python -m services.edge.score <session folder> [--run RUN_ID] [--tolerance SECONDS]

Reads <session>/labels.csv (DATA_CONTRACTS.md section 14) and one run's frames.csv, shots.csv and
tracks.csv, joins them through `t_video`, and prints H1 and H3b next to their thresholds. H3 and H4
are printed as not scorable: labels.csv has no field for what they need (D-043). A hypothesis whose
logs do not exist yet (shots.csv arrives with slice R3, a numbered tracks.csv with R5) is also
printed as not scorable, never as a pass or a zero.
"""

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from services.edge.contract import LABEL_EVENTS, LABELS_COLUMNS

# Placeholders: no source gives a matching tolerance (spec FR-013 points to the research note, which
# has none), so these are chosen, not measured. D-043.
TOLERANCE_S = 1.0  # a detected shot matches an attempt label within this many seconds
OUTCOME_WINDOW_S = 6.0  # the make or miss label that belongs to an attempt follows it by this much
IDENTITY_WINDOW_S = 5.0  # seconds before a leave and after a return in which the ID is read

# Thresholds of the decision record (section 4) and spec FR-006, FR-007, FR-010, FR-012.
H1_FOUND_MIN, H1_RIGHT_MIN, H1_FLOOR = 0.85, 0.90, 0.70
H3_MIN = 0.80
H3B_MIN = 0.80
H4_MAX_M = 0.5
MIN_ATTEMPTS = 30  # "30 or more shots, hand-counted"
MIN_RETURNS = 10  # H3b is "8 of 10 returns"

REQUIRED_LABEL_COLUMNS = ("time_s", "event", "player_number")


class ScoreError(Exception):
    """The inputs cannot be scored. The message says which file and what is wrong."""


@dataclass(frozen=True)
class Label:
    time_s: float
    event: str
    player_number: int | None
    note: str


@dataclass(frozen=True)
class H1:
    attempts: int  # attempt labels
    found: int  # of them matched by a shot
    scored: int  # found attempts that have a make or miss label
    right: int  # of those, called as labelled; an uncertain call is not right
    uncertain: int  # found attempts called uncertain
    false_attempts: int  # shots no attempt label matches
    no_outcome: int  # found attempts with no make or miss label (not scored for the call)
    source: str  # video | video+sensor

    @property
    def found_rate(self) -> float:
        return self.found / self.attempts

    @property
    def right_rate(self) -> float | None:
        return self.right / self.scored if self.scored else None

    @property
    def verdict(self) -> str:
        if self.right_rate is None:
            return "undecided: no make or miss labels for the attempts found"
        if self.found_rate >= H1_FOUND_MIN and self.right_rate >= H1_RIGHT_MIN:
            return "continue"
        if min(self.found_rate, self.right_rate) >= H1_FLOOR:
            return "add the rim sensor"
        return "stop vision-only"


@dataclass(frozen=True)
class H3b:
    returns: int  # return labels
    assessed: int  # returns whose player had a numbered track before leaving
    kept: int  # of those, the same track carries the number after the return
    not_assessable: int

    @property
    def rate(self) -> float | None:
        return self.kept / self.assessed if self.assessed else None

    @property
    def passed(self) -> bool:
        return self.rate is not None and self.rate >= H3B_MIN


# -- reading -------------------------------------------------------------------------------


def load_labels(path: Path) -> list[Label]:
    try:
        f = open(path, newline="", encoding="utf-8")
    except OSError as e:
        raise ScoreError(f"cannot read {path}: {e.strerror or e}") from e
    with f:
        reader = csv.DictReader(f)
        missing = [c for c in REQUIRED_LABEL_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ScoreError(
                f"labels.csv needs the columns {', '.join(LABELS_COLUMNS)} (note is optional); "
                f"found {reader.fieldnames}"
            )
        labels = []
        for row in reader:
            n = reader.line_num
            try:
                time_s = float(row["time_s"])
            except ValueError:
                raise ScoreError(
                    f"labels.csv line {n}: time_s {row['time_s']!r} is not a number"
                ) from None
            if not time_s >= 0:
                raise ScoreError(f"labels.csv line {n}: time_s must be >= 0, got {time_s}")
            event = (row["event"] or "").strip()
            if event not in LABEL_EVENTS:
                raise ScoreError(
                    f"labels.csv line {n}: event {event!r} is not one of {', '.join(LABEL_EVENTS)}"
                )
            number = (row["player_number"] or "").strip()
            try:
                player = int(number) if number else None
            except ValueError:
                raise ScoreError(
                    f"labels.csv line {n}: player_number {number!r} is not a number"
                ) from None
            labels.append(Label(time_s, event, player, (row.get("note") or "").strip()))
    return labels


def run_dir(folder: Path, run_id: str | None) -> Path:
    if run_id:
        path = folder / "runs" / run_id
        if not path.is_dir():
            raise ScoreError(f"{folder} has no run {run_id}")
        return path
    try:
        runs = json.loads((folder / "session.json").read_text(encoding="utf-8"))["runs"]
    except (OSError, ValueError, KeyError):
        runs = sorted(p.name for p in (folder / "runs").glob("*") if p.is_dir())
    if not runs:
        raise ScoreError(f"{folder} has no runs")
    return folder / "runs" / runs[-1]  # the latest: a replay is added after the live run


def _rows(path: Path) -> list[dict] | None:
    if not path.is_file():
        return None
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def frame_times(run: Path) -> dict[int, float]:
    """frame seq -> time in the recorded video, the key labels.csv is joined on."""
    rows = _rows(run / "frames.csv")
    if rows is None:
        raise ScoreError(f"{run} has no frames.csv")
    times = {int(r["seq"]): float(r["t_video"]) for r in rows if r.get("t_video")}
    if not times:
        raise ScoreError(
            f"{run / 'frames.csv'} has no t_video values, so labels cannot be joined to frames: "
            "record the session (video.mp4) or replay its video"
        )
    return times


# -- scoring -------------------------------------------------------------------------------


def _match(targets: list[float], found: list[float], tolerance: float) -> dict[int, int]:
    """One-to-one: each target (by index) to the nearest unused found time within tolerance."""
    pairs = sorted(
        (abs(t - f), i, j)
        for i, t in enumerate(targets)
        for j, f in enumerate(found)
        if abs(t - f) <= tolerance
    )
    matched: dict[int, int] = {}
    used: set[int] = set()
    for _, i, j in pairs:
        if i not in matched and j not in used:
            matched[i] = j
            used.add(j)
    return matched


def score_h1(folder: Path, run_id: str | None = None, tolerance: float = TOLERANCE_S) -> H1 | None:
    """H1 from shots.csv and the attempt, make and miss labels; None when it cannot be scored."""
    run = run_dir(folder, run_id)
    shot_rows = _rows(run / "shots.csv")
    labels = load_labels(folder / "labels.csv")
    attempts = sorted((lab for lab in labels if lab.event == "attempt"), key=lambda x: x.time_s)
    if shot_rows is None or not attempts:
        return None
    times = frame_times(run)
    shots = []
    for r in shot_rows:
        seq = int(r["seq"])
        if seq not in times:
            raise ScoreError(f"shots.csv shot {r['shot_id']}: frame seq {seq} is not in frames.csv")
        shots.append((times[seq], r["call"]))
    matched = _match([a.time_s for a in attempts], [t for t, _ in shots], tolerance)
    outcomes = sorted(
        (lab for lab in labels if lab.event in ("make", "miss")), key=lambda x: x.time_s
    )
    scored = right = uncertain = no_outcome = 0
    for i, j in matched.items():
        call = shots[j][1]
        uncertain += call == "uncertain"
        start = attempts[i].time_s
        end = start + OUTCOME_WINDOW_S
        if i + 1 < len(attempts):
            end = min(end, attempts[i + 1].time_s)
        expected = next((o.event for o in outcomes if start <= o.time_s < end), None)
        if expected is None:
            no_outcome += 1
            continue
        scored += 1
        right += call == expected
    source = (
        "video+sensor"
        if any("sensor" in (r.get("call_source") or "") for r in shot_rows)
        else "video"
    )
    return H1(len(attempts), len(matched), scored, right, uncertain,
              len(shots) - len(matched), no_outcome, source)  # fmt: skip


def score_h3b(folder: Path, run_id: str | None = None) -> H3b | None:
    """H3b from the leave and return labels and the player numbers in tracks.csv; None when there
    are no returns or no track carries a number yet (the identity layer is slice R5)."""
    run = run_dir(folder, run_id)
    labels = load_labels(folder / "labels.csv")
    returns = sorted((lab for lab in labels if lab.event == "return"), key=lambda x: x.time_s)
    track_rows = _rows(run / "tracks.csv")
    if not returns or track_rows is None:
        return None
    times = frame_times(run)
    seen = [  # (video time, track id, number)
        (times[int(r["seq"])], r["track_id"], int(r["player_number"]))
        for r in track_rows
        if r.get("player_number") and int(r["seq"]) in times
    ]
    if not seen:
        return None
    leaves = sorted((lab for lab in labels if lab.event == "leave"), key=lambda x: x.time_s)
    assessed = kept = 0
    for ret in returns:
        leave = next(
            (lv for lv in reversed(leaves)
             if lv.player_number == ret.player_number and lv.time_s < ret.time_s),
            None,
        )  # fmt: skip
        if ret.player_number is None or leave is None:
            continue
        before = {tid for t, tid, n in seen if n == ret.player_number
                  and leave.time_s - IDENTITY_WINDOW_S <= t <= leave.time_s}  # fmt: skip
        if not before:
            continue
        after = {tid for t, tid, n in seen if n == ret.player_number
                 and ret.time_s <= t < ret.time_s + IDENTITY_WINDOW_S}  # fmt: skip
        assessed += 1
        kept += bool(before & after)
    return H3b(len(returns), assessed, kept, len(returns) - assessed)


# -- report --------------------------------------------------------------------------------


def _pct(n: int, d: int) -> str:
    return f"{n}/{d} = {100 * n / d:.1f}%"


def format_report(folder: Path, run_id: str | None = None, tolerance: float = TOLERANCE_S) -> str:
    run = run_dir(folder, run_id)
    h1 = score_h1(folder, run.name, tolerance)
    h3b = score_h3b(folder, run.name)
    out = [f"scoring {folder.name} run {run.name}; a shot matches a label within {tolerance:g} s "
           "(a chosen value, not a measured one)"]  # fmt: skip
    if h1 is None:
        out.append("H1   not scorable: needs shots.csv in the run (slice R3) and attempt labels")
    else:
        right = "no outcome labels" if h1.right_rate is None else _pct(h1.right, h1.scored)
        ok = h1.verdict == "continue"
        basis = (
            "video alone, decides the threshold"
            if h1.source == "video"
            else "video + sensor, reported only; the video-alone score decides"
        )
        out.append(
            f"H1   attempts found {_pct(h1.found, h1.attempts)} (threshold >= 85%) | "
            f"called right {right} (threshold >= 90%) | {'PASS' if ok else 'FAIL'}: "
            f"{h1.verdict} ({basis})"
        )
        out.append(
            f"       uncertain {h1.uncertain} (counted wrong), false attempts {h1.false_attempts}, "
            f"found attempts with no make/miss label {h1.no_outcome}"
        )
        if h1.attempts < MIN_ATTEMPTS:
            out.append(
                f"       note: fewer than {MIN_ATTEMPTS} labelled attempts: not decisive for H1"
            )
    out.append(
        "H3   not scorable: labels.csv has no per-frame jersey-number labels "
        "(threshold >= 80% of tracks with the right number)"
    )
    if h3b is None:
        out.append(
            "H3b  not scorable: needs return labels and player numbers in tracks.csv "
            "(identity layer, slice R5) (threshold >= 80%, 8 of 10 returns)"
        )
    else:
        rate = "no assessable returns" if h3b.rate is None else _pct(h3b.kept, h3b.assessed)
        out.append(
            f"H3b  returns that kept the ID {rate} (threshold >= 80%) | "
            f"{'PASS' if h3b.passed else 'FAIL'}"
        )
        out.append(f"       {h3b.returns} returns labelled, {h3b.not_assessable} not assessable "
                   "(no numbered track before the leave)")  # fmt: skip
        if h3b.returns < MIN_RETURNS:
            out.append(f"       note: fewer than {MIN_RETURNS} returns: not decisive for H3b")
    out.append(
        "H4   not scorable: labels.csv has no taped-mark positions "
        f"(threshold: error <= {H4_MAX_M} m)"
    )
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m services.edge.score", description=__doc__)
    p.add_argument("session", type=Path, help="session folder (has labels.csv and runs/)")
    p.add_argument("--run", help="run id (default: the latest run of the session)")
    p.add_argument("--tolerance", type=float, default=TOLERANCE_S, metavar="SECONDS")
    args = p.parse_args(argv)
    try:
        print(format_report(args.session, args.run, args.tolerance))
    except ScoreError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
