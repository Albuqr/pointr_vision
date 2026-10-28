# Pointr

Pointr collects basketball training data from phone cameras at a court: it records each practice,
detects and tracks players, ball and rim, and turns that into per-athlete numbers for a coach. File
formats for every term below are in `docs/DATA_CONTRACTS.md`; this file holds meanings only.

## Recording

**Group**:
Every camera session started together for one practice, with the rim sensors and fusions that serve
them. What a coach would call "Tuesday's practice".
_Avoid_: practice, recording (for the whole), multi-camera session

**Drill type**:
The kind of activity a group records, such as a shooting drill or a 3x3 scrimmage; chosen from
presets or created with help. A group has one drill type, so a new drill means a new group.
_Avoid_: session type, practice type

**Session**:
What one camera recorded during one group (or alone, without a group): its source, video, runs and
events. One camera, one session.
_Avoid_: practice, drill (for one camera's part)

**Run**:
One pass of processing over a session's frames. A live session has one run; each replay adds a run
and never changes an earlier one.

**Replay**:
Processing a session's recorded video again as a new run.

**Device**:
One PC with Pointr installed: it owns its sessions, runs the cameras' processing and syncs to the
server. A phone is a camera, never a device.

**Camera**:
One phone (or webcam) pointed at the court, named by the operator within a group.

**Source**:
Where a session's frames come from: a camera, a network stream or a video file.

**Calibration**:
The mapping from one camera's image to court metres, made at the court before recording.

## People and identity

**Operator**:
The person who sets up the phones, calibrates and runs a session at the PC. In December a separate
person from the coach; later the coach is meant to be the operator too.
_Avoid_: user

**Coach**:
The person who reads the reports and changes practice from them.
_Avoid_: user

**Athlete**:
A registered person whose data Pointr keeps.
_Avoid_: registered player, player (for the person)

**Track**:
A temporary ID the tracker gives one detected person, shared by every camera of the group while it
records: the same track in two cameras is the same person. It is not linked to an athlete.
_Avoid_: player ID, athlete ID

**Leave / return**:
A player going out of one camera's view, and coming back into that same camera's view. Judged per
camera: out of one camera but in another's view is still a leave for the first.
_Avoid_: exit, re-entry

**Team**:
Athletes registered together, each with a shirt number unique within the team.

**Shirt number**:
The number registered for an athlete in a team.
_Avoid_: player number (for the registered one)

**Player number**:
The jersey or vest number read for a track by the identity layer. It can differ from the athlete's
shirt number (a borrowed vest); linking tracks to athletes matches one to the other.
_Avoid_: jersey ID

**Identity layer**:
The step after tracking that turns tracks into player numbers; its method is replaceable.

**Roster**:
Who takes part in one group: a subset of a team, or before teams exist the player numbers the
operator enters at setup. The startup check uses it.

## Shots

**Release**:
The moment the ball leaves the shooter's hand, found from video.

**Attempt**:
A release that the shot layer logs as a shot try, whether it goes in or not. A make is an attempt
that went in: 10 attempts with 4 makes is 4/10. "Shot" is used only in compounds (shot layer, shot
map, shooter).
_Avoid_: shot (as a countable noun)

**Shooter**:
The track that released the ball on an attempt.

**Call**:
The shot layer's verdict on an attempt: make, miss or uncertain. Uncertain is kept out of the
statistics and counts as wrong when scoring "called right".

**Make / miss / uncertain**:
The three values of a call, and only of a call.
_Avoid_: make (for a sensor make or a labelled make)

**Sensor make**:
A rim sensor's report that a ball passed through its rim. It is evidence for a call, not a call.

**Unmatched sensor make**:
A sensor make that no attempt's flight window contains: evidence of an attempt the video missed. It
is neither an attempt nor a make in the statistics, and counts against the video when scoring.

**Flight window**:
The interval around a release in which a sensor make is matched to that attempt.

## Hardware and time

**Rim sensor**:
The unit fixed at a rim that reports sensor makes; not a device.

**Gateway**:
The receiver attached to the PC that collects the rim sensors' messages.

**Clock domain**:
The single PC timeline on which every camera's frames and every sensor make are placed.

**Camera latency**:
The delay from a phone capturing a frame to the PC reading it, measured per camera.

**LED test**:
Flashing the rim sensor's light in view of the cameras to measure camera latency.

## Multi-camera

**Fusion**:
Combining, after the practice, every camera's readings of each shared track into one record per
player number. The cameras are matched live; fusion only combines and compares.

**Fusion record**:
The result of a fusion for one player number seen in the group.

**Camera disagreements**:
Where two cameras' records for one player number disagree, as found by a fusion.
_Avoid_: difference report

**Outage**:
A camera or a rim sensor stopping delivering, from when it stops to when it is back.

**Gap**:
The stretch of one camera session's timeline with no frames because of an outage; scoring leaves it
out.

## Setup and evaluation

**Startup check**:
One of five checks run before a session (camera, calibration, identity, ID persistence, sensor). A
failed check is recorded and never blocks the start while a camera is connected.

**Ground truth**:
Hand labels of what really happened in a session: attempts and whether each went in, leaves and
returns. A labelled make is ground truth, not a call.

**Scoring tool**:
Computes the hypothesis results from a session's logs and its ground truth.

**Report**:
What the coach reads about a group. Unqualified, "report" always means this.

**Run report**:
The numbers computed from one camera's run; an input to the report.

**Hypotheses H1–H8**:
The bets the December test checks, defined in `.scratch/pointr-vision/decision-record.md`.

**Phase R**:
The December test rig's own phase, with its own phase file and gate, run beside the numbered phases.
_Avoid_: Track R (collides with Track)
