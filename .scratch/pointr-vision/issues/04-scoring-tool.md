# 04 Hand labels and the scoring tool (R1)
Status: todo
Delivers: FR-013, AC-013.1; R1-A3 (fixture), R1-A4 (manual).
Blocked by: none (reads files; uses t_video from 02/03 when present)

`labels.csv` reader (DATA_CONTRACTS section 14, `LABELS_COLUMNS`, `LABEL_EVENTS`). `python -m
services.edge.score <session folder> [--run RUN_ID]` prints H1 (attempts found, calls right), H3b
(returns that keep the ID) and, because labels.csv has no field for them, H3 and H4 as "not scorable"
next to their thresholds. H1 is scored on video alone from `shots.csv` when it exists (R3 writes it);
without it the tool says so. Sensor-assisted H1 is reported from `events.csv` when it exists.

Open: tolerance for matching a detected event to a label, and the label fields H3 and H4 need
(DECISIONS D-042).
