# Glossary

Terms the December test rig (Track R) uses. Existing Pointr terms (session, run, source, calibration)
keep the meaning in `docs/DATA_CONTRACTS.md`.

**Track**: a temporary per-run ID given by the tracker to one detected person. _Avoid_: player ID,
athlete ID (those are linked to a person, a track is not).
**Track R**: the December test rig's own phase track (D-033), with its own phase file and gate.
**Camera process**: one OS process per phone, with its own capture, model, writer and session (D-022).
**Player number**: the jersey or vest number read for a track by the identity layer. _Avoid_: jersey ID.
**Identity layer**: the interface after the tracker that turns tracks into player numbers; the
method is chosen by `IDENTITY_METHOD`.
**Roster**: the player numbers the operator types at setup; the startup identity check uses it.
**Startup check**: one of five checks run before a session (camera, calibration, identity, ID
persistence, sensor). A failed check is recorded and never blocks the start while a camera is connected.
**Release**: the moment the ball leaves the shooter's hand, found from video.
**Attempt**: a release that the shot layer logs as a shot try.
**Make / miss / uncertain**: the shot layer's call. Uncertain is kept out of the statistics and
counts as wrong when scoring "called right".
**Rim sensor**: the microcontroller at the rim that reports a ball passing through (a make).
**Gateway**: the second ESP32 on the PC's USB port that receives the sensor's radio messages.
**Clock domain**: the PC's `perf_counter` timeline that frames and sensor events are placed on.
**Camera latency (L_k)**: the delay from a phone capturing a frame to the PC reading it, measured per
camera with the LED test.
**LED test**: the sensor's LED flashed in view of the cameras at random intervals, compared with the
first frame where it lights.
**Flight window**: the interval `[release − a, release + flight_max(d) + a]` in which a sensor make
event is matched to a shot.
**Fusion record**: the one-record-per-player result of merging two cameras after a session.
**Difference report**: where the two cameras' records for one player disagree.
**Gap**: a period when one phone's stream was down; left out of H3b and H6 scoring.
**Ground truth**: hand labels of attempts, makes, misses, leaves and returns, in the label CSV file.
**Scoring tool**: computes H1, H3, H3b and H4 from the logs and the ground truth.
**Hypotheses H1–H8**: defined in `.scratch/pointr-vision/decision-record.md` (H3b is the ID surviving
a leave and return).
