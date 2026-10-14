# Studio manual test: camera calibration and a calibrated recording

Step by step, front end first. Takes about 30 minutes with a tape measure. Nothing here has
been run on a real camera yet: the automated tests use fake cameras and synthetic clips, so
write down what you see, including anything that surprises you. Do not trust a number in this
file as an expected result; none of them is measured.

## 0. What you need

- The branch `v0-calibration`, checked out in the `pointr_review` folder. The built UI is committed
  (`services/app/ui/dist`), so you do not need Node.
- A camera that stays at one resolution for the whole test: a USB webcam, or a phone stream.
  Mount it so it does not move between calibrating and recording.
- A floor you can measure: tape, chalk or sticky marks, and a tape measure.
- The Python from your existing environment (the one in `pointr_vision/.venv`).

## 1. Start the Studio from this branch

If a Studio is already running (for example the one from `pointr_vision`, which is on a different
branch and does not have these fixes), stop it first with Ctrl+C in its terminal. Two Studios
cannot share port 8765.

```
cd C:\Users\davia\OneDrive\Desktop\projects\pointr_review
C:\Users\davia\OneDrive\Desktop\projects\pointr_vision\.venv\Scripts\python.exe -m services.app --out C:/pointr_sessions
```

Open http://127.0.0.1:8765/. The left menu has Record, Cameras, Calibration and Sessions.

Check: the page loads, and the bottom of the left menu says "Local device ready".

## 2. Add and test the camera (Cameras page)

1. Open **Cameras**. Fill the form:
   - camera ID, for example `cam1` (letters, digits, `_` and `-`, up to 32);
   - link: `usb` or `builtin` for a webcam (the source is then a camera index such as `0`), or
     `wifi` for a phone (the source is its stream URL, for example `http://192.168.1.20:4747/video`).
2. Press **Add camera**. The camera appears in the list.
3. Press **Test** on its row. Expected: a snapshot, its resolution and an fps figure. If it fails,
   the reason is shown under the row and stays there; fix the source before going on.

Write down the resolution the test shows.

## 3. Prepare the floor

1. Pick the origin: the near-left corner of the area you will measure, as the camera sees it.
   Court `x` runs along the length, `y` across the width. Both are in metres.
2. Put 8 marks on the floor and measure each one from the origin with the tape. Marks must be
   floor intersections or tape crosses you can click exactly, not moving things.
   - 4 marks for the fit, near the corners of the area you care about, spread out. They must not
     lie on one line and must not be bunched together.
   - 3 or more interior marks to hold out as check points. Each must be a different physical mark
     from every fit mark.
3. Write the table: mark number, x (m), y (m).

## 4. Calibrate (Calibration page)

1. Choose the camera. Set **Court model** to *Custom measured court* and type the length and width
   of your measured area in metres (the box that contains all your marks).
2. Press **Capture frame**.
   - Expected: the camera image appears, with a message such as "Frame captured at 1280 × 720, the
     size the recorder will use for this camera".
   - Check: the size matches what **Test** showed. If you will record with a phone stream, the size
     is whatever the stream sends.
3. For each mark, in order:
   1. Click the mark in the camera image. A numbered ring shows the pending point.
   2. Give it its court position, one of:
      - type the measured **X** and **Y** in metres in the boxes that appear, then press
        **Use coordinates**. This is the tape-measure route and works for any floor mark;
      - or click the place on the court diagram (the position under the cursor is used);
      - or click a landmark dot on the diagram to snap to it (only meaningful on a real court).
   3. The point is added to the table with the role `calibration`.
4. In the table, press the role button of the interior marks so they read **check**. Keep at least
   4 `calibration` and 2 `check` points. The count under the table reads "N points · N fit · N held
   out".
5. Look at the fit summary under the table:
   - **Fit mean**: how well the 4+ fit points agree with themselves (it should be tiny).
   - **Held-out mean** and **Held-out max**: the error on points that did not take part in the
     fit. This is the number that matters. Write both down.
   - If the court diagram lines drawn over the camera image do not sit on the real floor lines,
     the calibration is wrong even if the numbers look fine.
   - A message "Left out of the fit as outliers ... point N" means one of your fit points
     disagrees with the others by more than 0.1 m. Check that point's image position and its
     measured coordinates.
6. Press **Save calibration**. If the held-out mean is above **Maximum mean check error** (default
   0.5 m, at most 2 m), saving is refused unless you tick *Save anyway*; the file then records that it
   was forced. Do not force a calibration you intend to trust.
7. Optional: **Compare with fresh frame** compares the saved image with a new one. A high score
   means the camera moved.

### Things that should be refused (try at least two)

| Try | Expected |
|---|---|
| Add a check point at the same court X,Y as a fit point | refused with "same court position" |
| Click almost the same image pixel twice | refused with "same image position" |
| Four fit points on one line | refused with "collinear or bunched" |
| Four fit points all within a small patch | refused with "collinear or bunched" |
| Set Maximum mean check error to 3 and save | refused: the limit may be at most 2.0 m |
| Tick nothing and save with the held-out mean over the limit | refused, naming the limit |

Refusals appear as a message, never as a crash page.

## 5. Record with the calibration (Record page)

1. Open **Record**. Press **Start group**.
2. On the camera card, check:
   - "Calibrated · check 0.xx m" (the held-out mean you saved). If it says "Not calibrated ·
     positions in pixels", no calibration was found for this camera ID.
   - an orange "Calibration not used: ..." line means the saved calibration could not be read; the
     camera records uncalibrated and the other cameras are unaffected.
   - an error line under the card, for example both image sizes when the camera now delivers another
     size than the calibration. That camera does not record usable data; fix the camera or
     recalibrate. The other cameras keep recording.
3. Stand on each tape mark in turn for a few seconds (stand with your feet on the mark), then walk
   a known distance in a straight line, for example from one mark to another.
4. Press **Stop group**. Wait for the cards to show the recording saved.

Do not, during this recording: move the camera, change its resolution, or reconnect a phone stream
(see section 8).

## 6. Check the data

In `C:\pointr_sessions` there is one folder per camera, `<camera_id>_<session_id>`, with
`runs\<run_id>\tracks.csv`, `frames.csv`, `run.json` and `report.json`, and `session.json`.

1. Open `tracks.csv`. Columns include `x_m`, `y_m`, `calibration_id`, `position_method`,
   `in_court`.
   - While you stood on a mark, `x_m, y_m` should be near that mark's measured coordinates. The
     position is the bottom-centre of the person's box, which is close to the feet but is an
     estimate. Write down the difference for each mark: that is your real-world error, and the only
     figure to trust.
   - `in_court` is `true` or `false` (lowercase). Rows where a position could not be computed have
     empty `x_m`, `y_m` and `in_court`.
2. Open `session.json`. Events of kind `error` with text starting "calibration not used" or "frame
   size ... differs" explain a camera that recorded uncalibrated or lost its positions.
3. Open `report.json`, or read the summary printed in the terminal when the session ended. Expected:
   positions in `m`, speeds in `m/s`, the calibration ID, and the check error in the header line.
   Compare the path length of your straight-line walk with the distance you measured.

## 7. Resilience checks (optional, 10 minutes)

1. **Recalibrate while recording is idle**: capture a new frame, save a second calibration, start a
   recording. The card should show the new check error. A calibration saved while a recording is
   running only applies to the next recording.
2. **Corrupt calibration**: stop the Studio, open
   `%LOCALAPPDATA%\pointr\calibrations\<camera_id>\active.json` in a text editor and delete its last
   few characters, save, start the Studio and press Start group. Expected: the group starts, that
   camera shows "Calibration not used: ...", its `tracks.csv` has empty position columns. Restore
   the file (or save a new calibration) afterwards.
3. **Two cameras** (if you have them): corrupt one camera's `active.json` as above. Expected: the
   other camera still records calibrated.
4. **Wrong size**: calibrate with the camera at one resolution, then change the camera's resolution
   (for example another app setting) and start a recording. Expected: that camera fails with both
   sizes in its error line, and no usable data is written for it.

## 8. Known problems in this build (found by the reviews, not fixed yet)

These are tracked in `docs/BACKLOG.md`. Avoid them while testing, and tell me if you hit one.

- If a camera changes resolution in the middle of a recording (a phone reconnecting at another size),
  `tracks.csv` correctly leaves positions empty from that moment, but `report.json` still computes
  metres from those rows. Trust the report only for recordings where the resolution did not change.
- A camera that looks down at a far floor, so that the horizon is inside the picture, may be refused
  with "a calibration point lies on or beyond the horizon". Not covered by a test. If you see it,
  tell me the camera height and tilt.
- A calibration saved before the fixes in this branch may be refused; recalibrate.
- The overlay drawn over the camera image can look wrong for court corners behind the camera.
- After `pip install .` (not an editable install) calibrated recording fails because the schema file
  is not packaged. Run from the repository folder as in section 1.

## 9. What to send back

- The camera, link, resolution and mount.
- Your tape table (mark, x, y), the held-out mean and max shown by the Studio, and the per-mark
  difference you measured in `tracks.csv`.
- Any message in the UI that was unclear, any crash, and the contents of `session.json` events if
  something was refused.
