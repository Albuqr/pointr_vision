# B12: testing for degenerate fit-point geometry without refusing partial views

Question: how should `fit_calibration` (`services/edge/calibration/homography.py`) refuse
degenerate fit geometry (image px -> court m, `cv2.findHomography(..., cv2.RANSAC, 0.1)`)
without refusing a sideline phone's perspective-foreshortened view of half a court?

Installed versions (read 2026-10-28): `cv2.__version__` 5.0.0, numpy 2.4.6.

## Sources read, and what could not be read

| Id | Source | Read? |
|---|---|---|
| [HZ-TOC] | Hartley & Zisserman, MVG 2nd ed., official table of contents, `robots.ox.ac.uk/~vgg/hzbook/hzbook2/HZcontents.pdf` | yes |
| [HZ-TUT] | Hartley & Zisserman, CVPR 1999 tutorial "Multiple View Geometry" (authors' slides), `users.cecs.anu.edu.au/~hartley/Papers/CVPR99-tutorial/tutorial.pdf` | yes (text extracted; equations are partly lost) |
| [CRZ] | Criminisi, Reid, Zisserman, "A Plane Measuring Device", BMVC 1997, `bmva-archive.org.uk/bmvc/1997/papers/057/` (sections 5-8) | prose yes; equations are GIFs and could not be read |
| [CV-F] | OpenCV 5.0.0 `modules/geometry/src/fundam.cpp` (calib3d was split; the files moved to `modules/geometry`) | yes |
| [CV-P] | OpenCV 5.0.0 `modules/geometry/src/precomp.hpp`, `ptsetreg.cpp` | yes |
| [CV-U] | OpenCV 5.0.0 `modules/geometry/src/usac/degeneracy.cpp` | yes |
| [SN] | SoccerNet `sn-calibration` README (challenge evaluation) | yes |

Not readable: MVG chapters 4 and 5 themselves (not among the official sample chapters, which
are only Introduction, Epipolar geometry, Trifocal tensor, Bibliography, per the book page).
So the book's own wording of sec. 4.1 ("degenerate configurations"), 4.4 and 5.2 is **not
quoted here**; claims about them come from the same authors' tutorial [HZ-TUT] and from
[CRZ]. [HZ-TOC] confirms the section numbers: 4.1 DLT algorithm (p.88), 4.4 Transformation
invariance and normalization (p.104), 5.1 Bounds on performance, 5.2 Covariance of the
estimated transformation (p.138), 5.3 Monte Carlo estimation of covariance. Hartley's "In
defence of the 8-point algorithm" PDF was downloaded but its fonts did not extract. The
sports-field papers (Homayounfar 2017, Chen & Little 2019, Citraro 2020) could not be read:
CVF returned 403 and the arXiv PDFs did not extract to text. Their acceptance rules are
**unverified** and are not used below.

## 1. What the geometry actually requires

- Four point correspondences determine H uniquely "if (no three points collinear)"; any four
  points in general position map to any other four in general position [HZ-TUT, slide on
  computing a projective transformation]. The degenerate configuration is therefore *three of
  the four points on a line*, in either plane, not "the cloud is thin".
- For n > 4 points the same reasoning gives: H is undetermined when all points but one lie on
  one line (dropping the off-line point leaves a collinear set). This generalisation is our
  inference, not a quoted source.
- Overall thinness of the cloud is not a degeneracy. A trapezoid squashed by foreshortening
  has no three collinear points and determines H exactly. The brief's measurement agrees:
  with zero noise every fit the 0.1 ratio refuses has ~0 check error.

## 2. What OpenCV 5.0.0 checks (exact code)

`findHomography` [CV-F, lines ~296-350]:

- `if( method == 0 || npoints == 4 )` it calls `cb->runKernel(src, dst, H)` directly. **With
  exactly four fit points, no degeneracy check of any kind runs**, RANSAC or not, and no
  Levenberg-Marquardt refinement either (that block needs `npoints > 4`).
- Points are converted to `CV_32F` before fitting.
- With n > 4 and RANSAC, each random 4-sample goes through `getSubset` -> `checkSubset`
  (up to 10000 attempts) [CV-P]. The final refit on all inliers is **not** checked.

`HomographyEstimatorCallback::checkSubset` [CV-F]:

1. `haveCollinearPoints(ms1, count) || haveCollinearPoints(ms2, count)` -> reject. In
   [CV-P] this tests, for the last point i and every earlier pair (j, k),
   `fabs(dx2*dy1 - dy2*dx1) <= FLT_EPSILON*(fabs(dx1)+fabs(dy1)+fabs(dx2)+fabs(dy2))`.
   FLT_EPSILON = 1.19e-7, so this catches only *numerically exact* collinearity (the
   cross product is twice a triangle area; the tolerance is ~1e-7 x side length). It
   cannot catch clicked points that are 1-5 px off a line. Note it only tests triples
   containing the last point.
2. For `count == 4`: for the triples {0,1,2},{1,2,3},{0,2,3},{0,1,3}, count triples where
   `det(A)*det(B) < 0` (A, B = homogeneous 3x3 of the triple in source and destination).
   Reject unless that count is 0 or 4: orientation must be preserved by all triples or
   reversed by all. Cited in the code to Marquez-Neila et al., J. Real-Time Image Proc. 2013.

`runKernel` [CV-F]: shifts each point set to its centroid and scales x and y
**independently** so the mean |x| and mean |y| are 1 (anisotropic L1 normalisation); returns
0 (failure) only if a coordinate spread is below DBL_EPSILON. Then takes the smallest
eigenvector of AᵀA and denormalises.

USAC `HomographyDegeneracyImpl::isSampleGood` [CV-U] (not used by `cv2.RANSAC`): the same
orientation test written with line cross products, with `TOLERANCE = 2 * FLT_EPSILON`.

Takeaway: OpenCV offers no near-collinearity guard usable for clicked points, and for 4 points
none at all. The tool must do it.

## 3. The five candidate tests

### 3.1 Current rule: anisotropy ratio sqrt(λmin/λmax) >= 0.1

No source found that uses an anisotropy ratio of the point cloud as a degeneracy test. It is
scale-free, so it cannot relate to click noise, and it measures thinness of the whole cloud,
which §1 says is not the degenerate condition. Brief's measurement: of fits passing a 0.5 m
check, it refuses 14/15 in the 10-20 px thickness band and 105/141 in 20-40 px. On the
**court** side the ratio is less harmful (court coordinates are exact, not clicked) but still
tests thinness rather than 3-collinearity.

### 3.2 Absolute pixel thickness sqrt(λmin) >= N px

Ties to click noise (good), but still measures the whole cloud, not 3-of-4 collinearity: four
points can be thick overall with three on a line (a "T"), or thin with none collinear. Own
measurement (below): thickness separates good from bad fits much worse than the triple test.

### 3.3 Conditioning

- [HZ-TUT, "Normalization and 2D homography computation"]: "Condition number ... ratio of
  singular values of A"; "Bad condition number the reason for poor performance"; "Bad
  conditioning acts as a noise amplifier"; normalization = "Translate so centroid is at
  origin", "Scale so that RMS distance of points from origin is √2"; reference Hartley, "In
  defence of the 8-point algorithm". So the conditioning the authors mean is that of the
  **(normalised) DLT design matrix A**, not of H.
- **cond(H) is not meaningful as a degeneracy test.** H maps pixels to metres, so its
  singular values carry units; cond(H) changes with the unit choice while the mapping is the
  same. Own measurement (`condh.py`, one exact 4-point fit, sideline camera): cond(H) =
  7.79e3 with court in m, 7.69e5 in cm, 7.69e6 in mm, and 23.5 with image in px/1000. A good
  fit in mm is a hair under the current 1e7 limit. The brief's measurement agrees from the
  other side: near-collinear image points pass the cond(H) check with ~7 m check error.
  cond(H) = inf does still flag a truly singular H, so `np.linalg.cond` finite-ness can stay
  as a numeric sanity guard, not as a geometry rule.
- For a minimal 4-point fit A is 8x9 and its 9th singular value is 0 by construction; the
  informative quantity is the 8th singular value of the *normalised* A (the gap that defines
  the null space). Own measurement: s8/s1 < 0.01 -> 8% of fits pass 0.5 m, but its bands do
  not separate well above that (table below). No source gives a threshold.

### 3.4 Covariance / uncertainty propagation (MVG ch. 5, [CRZ])

- [CRZ sec. 5]: "we compute the covariance of the homography H estimated from n image-world
  point correspondences", noise "modelled as an homogeneous, isotropic Gaussian noise
  process"; the expression is derived by matrix perturbation of the smallest eigenvector of
  AᵀA and, unlike methods that invert AᵀA, "is well conditioned" when "only four
  correspondences are used". [CRZ sec. 6]: measurement uncertainty includes both "errors in
  the world and image points used to compute the homography" and "errors in the image points
  back projected"; "The first order analysis is assumed sufficient." [CRZ sec. 7]: "The
  covariance expression *predicts* uncertainty given the number of image-world computation
  points and their distribution", and the predicted and Monte Carlo ellipses "are almost
  overlapping" (their examples; we cannot see their noise levels).
- [HZ-TUT] shows the same idea empirically: a homography from 5 noisy matches applied to a
  6th point, 95% ellipses of the transferred point, normalised vs unnormalised.
- This is the only candidate that answers the operator's real question in metres, and it
  covers both causes of a meaningless fit: near-collinear triples *and* extrapolation far from
  the fit points. It needs an assumed click σ, which no source fixes for a phone image.

First-order propagation is simple to implement for a small tool: numerical Jacobian J (2 x
2n+2) of the transferred court point w.r.t. the clicked image coordinates (fit points plus
the query point), Σ = σ² J Jᵀ, report sqrt(trace Σ). (This is the forward-propagation form
of [CRZ]/MVG 5.2 with court points treated as exact; the numerical Jacobian is our choice.)

### 3.5 "Three of four collinear" test

Directly tests the configuration [HZ-TUT] names. Implementation in pixels: for every triple of
fit points, the smallest distance of one point from the line through the other two (for n > 4,
generalise to: for each point left out, the RMS distance of the remaining points from their
best-fit line, i.e. sqrt(λmin) of the n-1 subset). Because it is in pixels, the threshold can
be stated as a multiple of click noise. OpenCV's own version (§2) uses an exactness tolerance
of FLT_EPSILON and is useless for clicked points.

## 4. Own measurement (labelled; `propagate.py` in the session scratchpad)

Same synthetic setup as the brief: 1280x720 pinhole, 6 poses (sideline 1.5-4 m, behind
baseline, corner), FIBA full court, every 4-landmark fit subset with court ratio >= 0.1,
2,342 fits, two held-out checks, one draw of 1 px Gaussian noise on fit and check clicks,
plain DLT (what OpenCV does for 4 points). "Pass" = mean check error < 0.5 m.

| Test (bucket) | n | pass | median check err |
|---|---|---|---|
| min triple point-to-line distance 0-2 px | 364 | 0 (0%) | 21.8 m |
| 2-5 px | 148 | 2 (1%) | 3.8 m |
| 5-10 px | 206 | 17 (8%) | 1.8 m |
| 10-20 px | 521 | 93 (18%) | 1.1 m |
| 20-40 px | 564 | 221 (39%) | 0.65 m |
| 40+ px | 539 | 340 (63%) | 0.38 m |
| cloud thickness sqrt(λmin) 0-5 / 5-10 px | 11 / 58 | 0 / 0 | 13.3 / 11.1 m |
| first-order σ at checks (σ_click = 1 px) 0.1-0.3 m | 81 | 79 | 0.15-0.18 m |
| 0.3-0.5 m | 234 | 194 (83%) | 0.30 m |
| 0.5-1 m | 520 | 242 (47%) | 0.53 m |
| 1-2 m | 583 | 126 (22%) | 0.94 m |
| > 2 m | 924 | 32 (3%) | 5.4 m |

Correlation over all fits (log check error vs log measure): first-order σ 0.82, triple
distance -0.75, cloud thickness -0.30. Refusing thickness < 10 px refuses 69 fits (none
would pass) but keeps 1,600 failing fits; the triple test < 2 px refuses 364 (none would
pass). Caveats: one noise draw per fit, synthetic landmarks only, no lens distortion, no
RANSAC point dropping; the numbers rank the tests, they are not accuracy claims for Pointr.

## 5. Where the sources stop

- No primary source found gives a numeric threshold for "near-collinear" in pixels, for the
  normalised-A singular value, or for an acceptable propagated σ. [CRZ] predicts uncertainty;
  it does not say when to refuse.
- No source supports an anisotropy ratio or a cloud-thickness rule.
- Sports-field evaluations: SoccerNet scores a calibration by reprojection of pitch elements
  in pixels, "Completeness x JaC@5", JaC@t = TP/(TP+FN+FP) with a 5 px threshold, using only
  images with predicted parameters [SN]. It is an evaluation metric, not an accept/refuse
  rule, and is computed on full camera parameters, not a bare homography. The other sports
  papers could not be read (see above).

## Recommendation

1. **Drop the 0.1 anisotropy ratio on image points** (no source; refuses exact partial-view
   fits). Keep a court-side check only as the exact rule below, since court points are exact.
2. **Drop cond(H) > 1e7 as a geometry rule.** It is unit-dependent (§3.3). Keep only "H finite
   and invertible" plus the existing horizon (w > 0) check, which also implies OpenCV's
   orientation-consistency condition.
3. **Non-overridable geometry rule: no three fit points (near-)collinear, in pixels.** For
   every triple of RANSAC-inlier fit points, compute the distance of each point from the line
   through the other two; refuse if the minimum is below k·σ_click. With n > 4, refuse only if
   some leave-one-out subset is near-collinear (§3.5), since extra points can rescue a
   collinear triple. This is the configuration [HZ-TUT] names, and it is what OpenCV checks
   only to FLT_EPSILON. Apply the same test on the court side with a small metric tolerance.
   Threshold: the sources do **not** settle k. In our measurement a 2 px floor (k = 2 at
   σ = 1 px) refused 364 fits and none of them would have passed a 0.5 m check; between 2
   and 5 px 2 of 148 passed. A rule of "minimum triple distance >= 3 px" is a defensible
   start, labelled as tuned on synthetic data, to revisit after real clicks are measured.
4. **Report, and optionally gate, the first-order propagated position σ in metres** at the
   check points and over the area the camera will use (assumed σ_click, e.g. 1 px, written
   into the calibration record). It is the source-backed quantity ([CRZ], MVG 5.2) and the
   best predictor in our measurement. Because "Save anyway" may override only the check-error
   limit, a σ gate is a candidate for the last guard against a meaningless forced fit, e.g.
   refuse when predicted σ exceeds the 2 m maximum check-error limit (own measurement: 3% of
   such fits passed 0.5 m). That number is ours, not a source's: decide it in
   `docs/OPEN_QUESTIONS.md` / `DECISIONS.md` rather than silently.
5. Held-out check error stays the acceptance test; geometry rules only refuse fits that are
   undetermined, not fits that are thin.
