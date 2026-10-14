import { useCallback, useEffect, useMemo, useState } from "react";

type Camera = {
  camera_id: string;
  source: string;
  link: string;
  det_size?: number;
  track_lost_secs?: number;
  track_activation?: number;
  track_min_frames?: number;
};
type TestResult = {
  snapshot?: string;
  resolution?: number[];
  fps?: number | null;
  error?: string;
};
type CameraStatus = {
  camera_id: string;
  state: string;
  processed_fps: number | null;
  people: number;
  tracks: number;
  drops: number;
  preview_drops: number;
  health: string;
  last_event: { kind?: string; detail?: string; t_wall?: string } | null;
  session_folder: string | null;
  preview_port: number | null;
  error?: string | null;
  calibration_warning?: string | null;
  calibration?: { calibration_id: string; check_error_m: number } | null;
};
type Status = { running: boolean; cameras: CameraStatus[] };
type Session = {
  camera_id: string;
  group_id: string;
  status: string;
  folder: string;
  summary: string | null;
};
type Point = {
  id: string;
  image_px: [number, number];
  court_m: [number, number];
  role: "calibration" | "check";
};
type Court = {
  kind: "fiba_full" | "custom";
  length_m: number;
  width_m: number;
  landmarks: Record<string, [number, number]>;
};
type Fit = {
  point_errors_m: number[];
  calibration_mean_m: number;
  check_mean_m: number | null;
  check_max_m: number | null;
  projected_court_lines: number[][][];
  court: Court;
};
type CourtGeometry = {
  landmarks: Record<string, [number, number]>;
  lines: [number, number][][];
};
type CalibrationFrame = {
  token: string;
  url: string;
  width: number;
  height: number;
};
type Comparison = {
  audit_frame: string;
  fresh_frame: string;
  difference_score: number | null;
  warning: boolean;
};

async function request<T>(
  url: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const response = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok)
    throw new Error((await response.text()).replace(/^"|"$/g, ""));
  return response.json() as Promise<T>;
}

const emptyCamera: Camera = { camera_id: "cam1", source: "0", link: "builtin" };
export default function StudioApp() {
  const [page, setPage] = useState("Record");
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [status, setStatus] = useState<Status>({ running: false, cameras: [] });
  const [sessions, setSessions] = useState<Session[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [tested, setTested] = useState<Record<string, TestResult>>({});
  const [editing, setEditing] = useState<string | null>(null);
  const [form, setForm] = useState<Camera>(emptyCamera);
  const [selected, setSelected] = useState("");
  const [frame, setFrame] = useState<CalibrationFrame | null>(null);
  const [points, setPoints] = useState<Point[]>([]);
  const [undoPoint, setUndoPoint] = useState<Point | null>(null);
  const [pendingImage, setPendingImage] = useState<[number, number] | null>(
    null,
  );
  const [courtKind, setCourtKind] = useState<"fiba_full" | "custom">("custom");
  const [length, setLength] = useState(28);
  const [width, setWidth] = useState(15);
  const [maxError, setMaxError] = useState(0.5);
  const [saveAnyway, setSaveAnyway] = useState(false);
  const [fit, setFit] = useState<Fit | null>(null);
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [customX, setCustomX] = useState(0);
  const [customY, setCustomY] = useState(0);
  const [hoverPoint, setHoverPoint] = useState<number | null>(null);
  const [geometry, setGeometry] = useState<CourtGeometry | null>(null);
  // the diagram and the snap points come from the server's court model, the one the fit uses
  const landmarks: Record<string, [number, number]> =
    fit?.court.landmarks ?? geometry?.landmarks ?? {};

  const refresh = useCallback(async () => {
    try {
      const [nextCameras, nextStatus] = await Promise.all([
        request<Camera[]>("/api/cameras"),
        request<Status>("/api/status"),
      ]);
      setCameras(nextCameras);
      setStatus(nextStatus);
      setError("");
      setSelected((old) =>
        nextCameras.some((camera) => camera.camera_id === old)
          ? old
          : nextCameras[0]?.camera_id || "",
      );
    } catch (reason) {
      setError(String(reason));
    }
  }, []);

  useEffect(() => {
    let current = true;
    const query = new URLSearchParams({
      kind: courtKind,
      length_m: String(length),
      width_m: String(width),
    });
    request<CourtGeometry>(`/api/court?${query}`)
      .then((next) => current && setGeometry(next))
      .catch(() => current && setGeometry(null)); // e.g. a dimension mid-edit: no diagram yet
    return () => {
      current = false;
    };
  }, [courtKind, length, width]);

  useEffect(() => {
    void refresh();
    const timer = setInterval(() => void refresh(), 1200);
    return () => clearInterval(timer);
  }, [refresh]);

  async function action(url: string, method = "POST", body?: unknown) {
    try {
      await request(url, method, body);
      setError("");
      setNotice("Changes saved.");
      await refresh();
    } catch (reason) {
      setError(String(reason));
    }
  }

  async function loadSessions() {
    try {
      setSessions(await request<Session[]>("/api/sessions"));
    } catch (reason) {
      setError(String(reason));
    }
  }

  async function submitCamera(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await action(
      editing ? `/api/cameras/${editing}` : "/api/cameras",
      editing ? "PUT" : "POST",
      form,
    );
    setEditing(null);
    setForm(emptyCamera);
  }

  async function captureFrame() {
    if (!selected) return;
    try {
      const response = await fetch(
        `/api/cameras/${selected}/calibration/frame`,
      );
      if (!response.ok) throw new Error(await response.text());
      const blob = await response.blob();
      setFrame({
        token: response.headers.get("X-Frame-Token") ?? "",
        url: URL.createObjectURL(blob),
        width: Number(response.headers.get("X-Frame-Width")),
        height: Number(response.headers.get("X-Frame-Height")),
      });
      setPoints([]);
      setPendingImage(null);
      setFit(null);
      setComparison(null);
      setNotice(
        `Frame captured at ${response.headers.get("X-Frame-Width")} × ${response.headers.get("X-Frame-Height")}, the size the recorder will use for this camera. A recording refuses a calibration made at another size.`,
      );
      setError("");
    } catch (reason) {
      setError(String(reason));
    }
  }

  const fitPayload = useMemo(
    () => ({
      frame_token: frame?.token,
      court_kind: courtKind,
      length_m: length,
      width_m: width,
      max_check_error_m: maxError,
      save_anyway: saveAnyway,
      points: points.map(({ id, ...point }) => point),
    }),
    [frame, courtKind, length, width, maxError, saveAnyway, points],
  );

  async function runFit(save = false) {
    if (!selected) return;
    try {
      const result = await request<Fit>(
        `/api/cameras/${selected}/calibration${save ? "" : "/fit"}`,
        save ? "PUT" : "POST",
        fitPayload,
      );
      setFit(result);
      setNotice(
        save
          ? "Calibration saved for this camera."
          : "Fit updated. Check the held-out points before saving.",
      );
      setError("");
    } catch (reason) {
      setError(String(reason));
    }
  }

  useEffect(() => {
    if (
      !frame ||
      !selected ||
      points.filter((point) => point.role === "calibration").length < 4
    ) {
      return;
    }
    const timer = window.setTimeout(() => {
      void request<Fit>(
        `/api/cameras/${selected}/calibration/fit`,
        "POST",
        fitPayload,
      )
        .then((result) => {
          setFit(result);
          setError("");
        })
        .catch((reason: unknown) => setError(String(reason)));
    }, 180);
    return () => window.clearTimeout(timer);
  }, [frame, selected, points, fitPayload]);

  useEffect(() => {
    return () => {
      if (frame) URL.revokeObjectURL(frame.url);
    };
  }, [frame]);

  function markImage(event: React.MouseEvent<HTMLButtonElement>) {
    if (!frame) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const x = Math.round(
      ((event.clientX - rect.left) * frame.width) / rect.width,
    );
    const y = Math.round(
      ((event.clientY - rect.top) * frame.height) / rect.height,
    );
    setPendingImage([x, y]);
    setNotice(
      "Image point selected. Click its matching location on the court, or enter coordinates below.",
    );
  }

  function addPoint(x: number, y: number) {
    if (!pendingImage) return;
    setPoints((old) => [
      ...old,
      {
        id: crypto.randomUUID(),
        image_px: pendingImage,
        court_m: [Number(x.toFixed(3)), Number(y.toFixed(3))],
        role: "calibration",
      },
    ]);
    setPendingImage(null);
    setFit(null);
  }

  async function compare() {
    try {
      setComparison(
        await request<Comparison>(
          `/api/cameras/${selected}/calibration/compare`,
        ),
      );
    } catch (reason) {
      setError(String(reason));
    }
  }

  function changePage(item: string) {
    setPage(item);
    setError("");
    setNotice("");
    if (item === "Sessions") void loadSessions();
  }

  return (
    <div className="studio-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">P</span>
          <span>
            <b>Pointr</b>
            <small>LOCAL STUDIO</small>
          </span>
        </div>
        <div className="side-label">WORKSPACE</div>
        <nav aria-label="Main navigation">
          {["Record", "Cameras", "Calibration", "Sessions"].map((item, i) => (
            <button
              type="button"
              className={page === item ? "nav-item active" : "nav-item"}
              key={item}
              onClick={() => changePage(item)}
            >
              <span className="nav-index">0{i + 1}</span>
              {item}
            </button>
          ))}
        </nav>
        <div className="side-bottom">
          <span className={status.running ? "pulse on" : "pulse"} />
          {status.running ? "Recording group active" : "Local device ready"}
          <small>Data stays on this computer</small>
        </div>
      </aside>
      <main className="workspace">
        <header className="topbar">
          <div>
            <div className="eyebrow">POINTR V0 / {page.toUpperCase()}</div>
            <h1>{page === "Record" ? "Recording" : page}</h1>
          </div>
          <div className="top-status">
            <span
              className={status.running ? "status-dot live" : "status-dot"}
            />
            {status.running ? "Group recording" : "Not recording"}
          </div>
        </header>
        {(error || notice) && (
          <div role="status" className={error ? "notice error-box" : "notice"}>
            {error || notice}
            <button
              type="button"
              aria-label="Dismiss message"
              onClick={() => {
                setError("");
                setNotice("");
              }}
            >
              ×
            </button>
          </div>
        )}

        {page === "Cameras" && (
          <section className="page-content">
            <div className="section-heading">
              <div>
                <div className="eyebrow">INPUT SOURCES</div>
                <h2>Camera setup</h2>
                <p>
                  Configure each view once. A phone stream can only have one
                  viewer.
                </p>
              </div>
              <span className="count-pill">{cameras.length} configured</span>
            </div>
            <div className="camera-layout">
              <form
                className="form-panel"
                onSubmit={(event) => void submitCamera(event)}
              >
                <h3>{editing ? "Edit camera" : "Add a camera"}</h3>
                <label>
                  Camera name
                  <input
                    required
                    value={form.camera_id}
                    onChange={(event) =>
                      setForm({ ...form, camera_id: event.target.value })
                    }
                    placeholder="cam1"
                  />
                </label>
                <label>
                  Connection type
                  <select
                    value={form.link}
                    onChange={(event) =>
                      setForm({ ...form, link: event.target.value })
                    }
                  >
                    <option value="builtin">Built-in camera</option>
                    <option value="usb">USB camera</option>
                    <option value="wifi">Wi-Fi phone</option>
                    <option value="file">Video file</option>
                  </select>
                </label>
                <label>
                  {form.link === "wifi"
                    ? "Phone stream URL"
                    : form.link === "builtin" || form.link === "usb"
                      ? "Camera index"
                      : "Video path"}
                  <input
                    required
                    value={form.source}
                    onChange={(event) =>
                      setForm({ ...form, source: event.target.value })
                    }
                    placeholder={
                      form.link === "wifi"
                        ? "http://192.168.1.20:4747/video"
                        : "0"
                    }
                  />
                </label>
                <details>
                  <summary>Detection and tracking options</summary>
                  <div className="option-grid">
                    <label>
                      Detection size
                      <input
                        type="number"
                        min="32"
                        step="32"
                        value={form.det_size ?? ""}
                        onChange={(event) =>
                          setForm({
                            ...form,
                            det_size: event.target.value
                              ? Number(event.target.value)
                              : undefined,
                          })
                        }
                        placeholder="Model default"
                      />
                    </label>
                    <label>
                      Lost track (seconds)
                      <input
                        type="number"
                        min="0.01"
                        step="0.1"
                        value={form.track_lost_secs ?? ""}
                        onChange={(event) =>
                          setForm({
                            ...form,
                            track_lost_secs: event.target.value
                              ? Number(event.target.value)
                              : undefined,
                          })
                        }
                        placeholder="1.0"
                      />
                    </label>
                    <label>
                      Track activation
                      <input
                        type="number"
                        min="0.01"
                        max="1"
                        step="0.01"
                        value={form.track_activation ?? ""}
                        onChange={(event) =>
                          setForm({
                            ...form,
                            track_activation: event.target.value
                              ? Number(event.target.value)
                              : undefined,
                          })
                        }
                        placeholder="0.7"
                      />
                    </label>
                    <label>
                      Minimum frames
                      <input
                        type="number"
                        min="1"
                        step="1"
                        value={form.track_min_frames ?? ""}
                        onChange={(event) =>
                          setForm({
                            ...form,
                            track_min_frames: event.target.value
                              ? Number(event.target.value)
                              : undefined,
                          })
                        }
                        placeholder="2"
                      />
                    </label>
                  </div>
                </details>
                <button className="primary" type="submit">
                  {editing ? "Save changes" : "Add camera"}
                </button>
                {editing && (
                  <button
                    type="button"
                    className="quiet"
                    onClick={() => {
                      setEditing(null);
                      setForm(emptyCamera);
                    }}
                  >
                    Cancel edit
                  </button>
                )}
              </form>
              <div className="camera-list">
                <h3>Your cameras</h3>
                {cameras.length === 0 && (
                  <p className="empty">
                    No cameras yet. Add a source to get started.
                  </p>
                )}
                {cameras.map((camera) => (
                  <article className="camera-row" key={camera.camera_id}>
                    <div>
                      <b>{camera.camera_id}</b>
                      <span>
                        {camera.link} · {camera.source}
                      </span>
                    </div>
                    <div className="row-actions">
                      <button
                        type="button"
                        onClick={async () => {
                          try {
                            setTested({
                              ...tested,
                              [camera.camera_id]: await request<TestResult>(
                                `/api/cameras/${camera.camera_id}/test`,
                                "POST",
                              ),
                            });
                          } catch (reason) {
                            setTested({
                              ...tested,
                              [camera.camera_id]: { error: String(reason) },
                            });
                          }
                        }}
                      >
                        Test
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setEditing(camera.camera_id);
                          setForm(camera);
                        }}
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        className="danger-text"
                        onClick={() =>
                          void action(
                            `/api/cameras/${camera.camera_id}`,
                            "DELETE",
                          )
                        }
                      >
                        Remove
                      </button>
                    </div>
                    {tested[camera.camera_id] && (
                      <div className="test-result">
                        {tested[camera.camera_id].snapshot ? (
                          <img
                            alt={`${camera.camera_id} test snapshot`}
                            src={`data:image/jpeg;base64,${tested[camera.camera_id].snapshot}`}
                          />
                        ) : (
                          <p>{tested[camera.camera_id].error}</p>
                        )}
                        <small>
                          {tested[camera.camera_id].resolution?.join(" × ")}{" "}
                          {tested[camera.camera_id].fps?.toFixed(1)} fps
                        </small>
                      </div>
                    )}
                  </article>
                ))}
              </div>
            </div>
          </section>
        )}

        {page === "Record" && (
          <section className="page-content">
            <div className="section-heading">
              <div>
                <div className="eyebrow">SESSION CONTROL</div>
                <h2>
                  {status.running
                    ? "Recording in progress"
                    : "Ready when you are"}
                </h2>
                <p>
                  Start all configured cameras together. Recording continues if
                  you close this browser tab.
                </p>
              </div>
              <div className="record-actions">
                <button
                  className="primary"
                  type="button"
                  disabled={status.running || cameras.length === 0}
                  onClick={() => void action("/api/recording/start")}
                >
                  Start group
                </button>
                <button
                  className="stop-button"
                  type="button"
                  disabled={!status.running}
                  onClick={() => void action("/api/recording/stop")}
                >
                  Stop group
                </button>
              </div>
            </div>
            {!status.running && status.cameras.length === 0 && (
              <div className="empty-state">
                <span>01</span>
                <b>No camera group is active</b>
                <p>
                  Add your camera sources, then return here to start recording.
                </p>
                <button type="button" onClick={() => changePage("Cameras")}>
                  Set up cameras
                </button>
              </div>
            )}
            <div className="record-grid">
              {status.cameras.map((camera) => (
                <article className="feed" key={camera.camera_id}>
                  <div className="feed-head">
                    <div>
                      <span className="eyebrow">CAMERA</span>
                      <h3>{camera.camera_id}</h3>
                    </div>
                    <span className={`state ${camera.state}`}>
                      {camera.state}
                    </span>
                  </div>
                  {camera.preview_port ? (
                    <img
                      className="preview"
                      alt={`${camera.camera_id} live annotated preview`}
                      src={`/api/cameras/${camera.camera_id}/preview/mjpeg`}
                    />
                  ) : (
                    <div className="preview-placeholder">
                      {camera.state === "starting"
                        ? "Opening source…"
                        : "Preview unavailable"}
                    </div>
                  )}
                  <div className="metric-strip">
                    <span>
                      <b>{camera.processed_fps?.toFixed(1) ?? "—"}</b>
                      <small>FPS</small>
                    </span>
                    <span>
                      <b>{camera.people}</b>
                      <small>PEOPLE</small>
                    </span>
                    <span>
                      <b>{camera.tracks}</b>
                      <small>TRACKS</small>
                    </span>
                    <span>
                      <b>{camera.drops}</b>
                      <small>DROPS</small>
                    </span>
                  </div>
                  <div className="feed-foot">
                    <span className={`health-tag ${camera.health}`}>
                      {camera.health}
                    </span>
                    <span>
                      {camera.calibration
                        ? `Calibrated · check ${camera.calibration.check_error_m.toFixed(2)} m`
                        : "Not calibrated · positions in pixels"}
                    </span>
                  </div>
                  {camera.calibration_warning && (
                    <p className="feed-warning" role="alert">
                      Calibration not used: {camera.calibration_warning}
                    </p>
                  )}
                  {camera.error && <p className="feed-error">{camera.error}</p>}
                  {camera.last_event && (
                    <small className="last-event">
                      Last event: {JSON.stringify(camera.last_event)}
                    </small>
                  )}
                  {camera.session_folder && (
                    <small className="session-path">
                      {camera.session_folder}
                    </small>
                  )}
                  {!status.running &&
                    ["interrupted", "ended"].includes(camera.state) && (
                      <p className="result-clean">
                        Recording saved · {camera.state}
                      </p>
                    )}
                  {!status.running &&
                    camera.state === "error" &&
                    !camera.error && (
                      <p className="error">
                        Camera process ended with an error.
                      </p>
                    )}
                </article>
              ))}
            </div>
          </section>
        )}

        {page === "Calibration" && (
          <section className="page-content calibration-page">
            <div className="section-heading">
              <div>
                <div className="eyebrow">PART 5B · CAMERA GEOMETRY</div>
                <h2>Map the floor to metres</h2>
                <p>
                  Mark known floor points in the image, then pair them with
                  measured court coordinates.
                </p>
              </div>
              <span className="count-pill">
                {status.running
                  ? "Camera can be sampled live"
                  : "Camera must be stationary"}
              </span>
            </div>
            <div className="calibration-controls">
              <label>
                Camera
                <select
                  value={selected}
                  onChange={(event) => {
                    setSelected(event.target.value);
                    setFrame(null);
                    setPoints([]);
                    setFit(null);
                  }}
                >
                  <option value="">Choose camera</option>
                  {cameras.map((camera) => (
                    <option key={camera.camera_id} value={camera.camera_id}>
                      {camera.camera_id} · {camera.link}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Court model
                <select
                  value={courtKind}
                  onChange={(event) => {
                    setCourtKind(event.target.value as "fiba_full" | "custom");
                    setFit(null);
                  }}
                >
                  <option value="custom">Custom measured court</option>
                  <option value="fiba_full">FIBA full court</option>
                </select>
              </label>
              <label>
                Length (m)
                <input
                  type="number"
                  min="0.1"
                  step="0.1"
                  value={length}
                  disabled={courtKind === "fiba_full"}
                  onChange={(event) => setLength(Number(event.target.value))}
                />
              </label>
              <label>
                Width (m)
                <input
                  type="number"
                  min="0.1"
                  step="0.1"
                  value={width}
                  disabled={courtKind === "fiba_full"}
                  onChange={(event) => setWidth(Number(event.target.value))}
                />
              </label>
              <button
                type="button"
                className="primary"
                disabled={!selected}
                onClick={() => void captureFrame()}
              >
                Capture frame
              </button>
            </div>
            <div className="axis-note">
              <b>Axes:</b> origin is the near-left corner. +X runs along court
              length; +Y runs across court width. Use measured metres for a
              custom floor.
            </div>
            {frame ? (
              <>
                <div className="calibration-workspace">
                  <div className="work-panel">
                    <div className="panel-title">
                      <div>
                        <span className="eyebrow">01 / CAMERA IMAGE</span>
                        <h3>Click a floor landmark</h3>
                      </div>
                      <span>
                        {frame.width} × {frame.height}px
                      </span>
                    </div>
                    <div
                      className="image-stage"
                      style={{
                        aspectRatio: `${frame.width} / ${frame.height}`,
                      }}
                    >
                      <button
                        type="button"
                        className="frame-capture"
                        aria-label="Choose floor point in camera image"
                        onClick={markImage}
                      >
                        <img
                          src={frame.url}
                          alt="Unannotated calibration frame"
                        />
                      </button>
                      <svg
                        viewBox={`0 0 ${frame.width} ${frame.height}`}
                        preserveAspectRatio="none"
                        aria-hidden="true"
                      >
                        {fit?.projected_court_lines.map((line) => (
                          <polyline
                            key={`${line[0]?.join("-")}-${line.at(-1)?.join("-")}`}
                            points={line.map((p) => p.join(",")).join(" ")}
                          />
                        ))}
                        {pendingImage && (
                          <circle
                            className="pending-point"
                            cx={pendingImage[0]}
                            cy={pendingImage[1]}
                            r={Math.max(frame.width / 130, 7)}
                          />
                        )}
                      </svg>
                      {points.map((point, index) => (
                        <button
                          key={point.id}
                          type="button"
                          aria-label={`Calibration point ${index + 1}`}
                          className={`frame-point ${hoverPoint === index ? "highlight" : ""}`}
                          style={{
                            left: `${(point.image_px[0] / frame.width) * 100}%`,
                            top: `${(point.image_px[1] / frame.height) * 100}%`,
                          }}
                          onMouseEnter={() => setHoverPoint(index)}
                          onMouseLeave={() => setHoverPoint(null)}
                          onFocus={() => setHoverPoint(index)}
                          onBlur={() => setHoverPoint(null)}
                        >
                          {index + 1}
                        </button>
                      ))}
                    </div>
                    <small className="helper">
                      Use floor intersections, not moving players. Spread points
                      across the visible area.
                    </small>
                  </div>
                  <div className="work-panel">
                    <div className="panel-title">
                      <div>
                        <span className="eyebrow">02 / COURT MODEL</span>
                        <h3>Pair with a court point</h3>
                      </div>
                      <span>
                        {length} × {width} m
                      </span>
                    </div>
                    <div className="court-map-shell">
                      <svg
                        className="court-map"
                        viewBox="0 0 280 150"
                        role="img"
                        aria-label="Basketball court diagram"
                      >
                        <rect
                          x="1"
                          y="1"
                          width="278"
                          height="148"
                          rx="3"
                          className="court-fill"
                        />
                        {geometry?.lines.map((line, index) => (
                          <path
                            // biome-ignore lint/suspicious/noArrayIndexKey: fixed list from the server
                            key={index}
                            d={line
                              .map(
                                ([x, y], i) =>
                                  `${i === 0 ? "M" : "L"}${((x / length) * 280).toFixed(2)} ${((y / width) * 150).toFixed(2)}`,
                              )
                              .join(" ")}
                            className="court-lines"
                            fill="none"
                          />
                        ))}
                        {Object.entries(landmarks).map(([name, xy]) => {
                          return (
                            <g key={name} className="landmark">
                              <circle
                                cx={(xy[0] / length) * 280}
                                cy={(xy[1] / width) * 150}
                                r="3.2"
                              />
                              <title>
                                {name.replaceAll("_", " ")} ({xy[0].toFixed(2)},{" "}
                                {xy[1].toFixed(2)}) m
                              </title>
                            </g>
                          );
                        })}
                        {points.map((point, index) => (
                          <g key={point.id}>
                            <circle
                              className={`court-point ${hoverPoint === index ? "highlight" : ""}`}
                              cx={(point.court_m[0] / length) * 280}
                              cy={(point.court_m[1] / width) * 150}
                              r="4"
                            />
                            <text
                              x={(point.court_m[0] / length) * 280 + 5}
                              y={(point.court_m[1] / width) * 150 - 4}
                            >
                              {index + 1}
                            </text>
                          </g>
                        ))}
                      </svg>
                      <button
                        type="button"
                        className="court-coordinate-hit"
                        aria-label="Add a custom measured court point"
                        onClick={(event) => {
                          const rect =
                            event.currentTarget.getBoundingClientRect();
                          addPoint(
                            ((event.clientX - rect.left) / rect.width) * length,
                            ((event.clientY - rect.top) / rect.height) * width,
                          );
                        }}
                      />
                      {Object.entries(landmarks).map(([name, xy]) => {
                        return (
                          <button
                            key={name}
                            type="button"
                            className="court-landmark-hit"
                            style={{
                              left: `${(xy[0] / length) * 100}%`,
                              top: `${(xy[1] / width) * 100}%`,
                            }}
                            aria-label={`Snap to ${name.replaceAll("_", " ")}`}
                            title={name.replaceAll("_", " ")}
                            onClick={() => addPoint(...xy)}
                          />
                        );
                      })}
                      {points.map((point, index) => (
                        <button
                          key={point.id}
                          type="button"
                          className={`court-point-hit ${hoverPoint === index ? "highlight" : ""}`}
                          style={{
                            left: `${(point.court_m[0] / length) * 100}%`,
                            top: `${(point.court_m[1] / width) * 100}%`,
                          }}
                          aria-label={`Court point ${index + 1}`}
                          onMouseEnter={() => setHoverPoint(index)}
                          onMouseLeave={() => setHoverPoint(null)}
                          onFocus={() => setHoverPoint(index)}
                          onBlur={() => setHoverPoint(null)}
                        >
                          {index + 1}
                        </button>
                      ))}
                    </div>
                    <div className="court-axis">
                      <span>0 m · origin</span>
                      <span>+X {length} m</span>
                      <span>+Y {width} m</span>
                    </div>
                    {pendingImage && (
                      <div className="manual-point">
                        <span>
                          Selected image point: {pendingImage[0]},{" "}
                          {pendingImage[1]} px
                        </span>
                        <label>
                          X{" "}
                          <input
                            aria-label="Court X metres"
                            type="number"
                            step="0.01"
                            value={customX}
                            onChange={(e) => setCustomX(Number(e.target.value))}
                          />
                        </label>
                        <label>
                          Y{" "}
                          <input
                            aria-label="Court Y metres"
                            type="number"
                            step="0.01"
                            value={customY}
                            onChange={(e) => setCustomY(Number(e.target.value))}
                          />
                        </label>
                        <button
                          type="button"
                          onClick={() => addPoint(customX, customY)}
                        >
                          Use coordinates
                        </button>
                      </div>
                    )}
                    <small className="helper">
                      Click the diagram to place the point at a custom
                      coordinate. Click a named landmark to snap.
                    </small>
                  </div>
                </div>
                <div className="point-tools">
                  <div>
                    <b>{points.length} points</b>
                    <span>
                      {" "}
                      · {points.filter((p) => p.role === "calibration").length}{" "}
                      fit · {points.filter((p) => p.role === "check").length}{" "}
                      held out
                    </span>
                  </div>
                  <div>
                    <button
                      type="button"
                      disabled={!undoPoint}
                      onClick={() => {
                        if (undoPoint) {
                          setPoints((old) => [...old, undoPoint]);
                          setUndoPoint(null);
                          setFit(null);
                        }
                      }}
                    >
                      Undo delete
                    </button>
                    <button
                      type="button"
                      disabled={!pendingImage}
                      onClick={() => setPendingImage(null)}
                    >
                      Cancel point
                    </button>
                  </div>
                </div>
                <div className="point-table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>#</th>
                        <th>Image px</th>
                        <th>Court m</th>
                        <th>Role</th>
                        <th>Residual</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {points.map((point, index) => (
                        <tr key={point.id}>
                          <td>{index + 1}</td>
                          <td>{point.image_px.join(", ")}</td>
                          <td>{point.court_m.join(", ")}</td>
                          <td>
                            <button
                              type="button"
                              className="role-pill"
                              onClick={() => {
                                setPoints((old) =>
                                  old.map((p, i) =>
                                    i === index
                                      ? {
                                          ...p,
                                          role:
                                            p.role === "calibration"
                                              ? "check"
                                              : "calibration",
                                        }
                                      : p,
                                  ),
                                );
                                setFit(null);
                              }}
                            >
                              {point.role}
                            </button>
                          </td>
                          <td>
                            {fit
                              ? `${fit.point_errors_m[index]?.toFixed(3) ?? "—"} m`
                              : "—"}
                          </td>
                          <td>
                            <button
                              type="button"
                              className="danger-text"
                              onClick={() => {
                                setUndoPoint(point);
                                setPoints((old) =>
                                  old.filter((_, i) => i !== index),
                                );
                                setFit(null);
                              }}
                            >
                              Delete
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {points.length === 0 && (
                    <p className="empty">
                      Select a point in the image, then pair it on the court
                      diagram.
                    </p>
                  )}
                </div>
                <div className="fit-footer">
                  <label>
                    Maximum mean check error (m)
                    <input
                      type="number"
                      min="0.01"
                      max="2"
                      step="0.05"
                      value={maxError}
                      onChange={(event) => {
                        setMaxError(Number(event.target.value));
                        setFit(null);
                      }}
                    />
                  </label>
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={saveAnyway}
                      onChange={(event) => setSaveAnyway(event.target.checked)}
                    />{" "}
                    Save anyway if check error exceeds limit
                  </label>
                  <button
                    type="button"
                    onClick={() => void runFit()}
                    disabled={
                      points.filter((p) => p.role === "calibration").length < 4
                    }
                  >
                    Fit and inspect
                  </button>
                  <button
                    type="button"
                    className="primary"
                    onClick={() => void runFit(true)}
                    disabled={
                      points.filter((p) => p.role === "calibration").length <
                        4 ||
                      points.filter((p) => p.role === "check").length < 2 ||
                      (!!fit &&
                        fit.check_mean_m !== null &&
                        fit.check_mean_m > maxError &&
                        !saveAnyway)
                    }
                  >
                    Save calibration
                  </button>
                </div>
                {fit && (
                  <div
                    className={
                      fit.check_mean_m !== null && fit.check_mean_m > maxError
                        ? "fit-summary warn"
                        : "fit-summary"
                    }
                  >
                    <b>
                      {fit.check_mean_m !== null && fit.check_mean_m > maxError
                        ? "Check error exceeds limit"
                        : "Fit ready to save"}
                    </b>
                    <span>Fit mean {fit.calibration_mean_m.toFixed(3)} m</span>
                    <span>
                      Held-out mean{" "}
                      {fit.check_mean_m === null
                        ? "add check points"
                        : `${fit.check_mean_m.toFixed(3)} m`}
                    </span>
                    <span>
                      Held-out max{" "}
                      {fit.check_max_m === null
                        ? "not measured"
                        : `${fit.check_max_m.toFixed(3)} m`}
                    </span>
                  </div>
                )}
              </>
            ) : (
              <div className="empty-state">
                <span>STEP 01</span>
                <b>Capture a camera frame to begin</b>
                <p>
                  For a recording camera, Studio uses its existing capture
                  stream. It will not open a second phone viewer.
                </p>
              </div>
            )}
            {selected && (
              <div className="compare-panel">
                <div>
                  <b>Did the phone move?</b>
                  <p>
                    Compare the saved calibration image with a new frame. This
                    visual difference is a warning signal, not a recalibration.
                  </p>
                </div>
                <button type="button" onClick={() => void compare()}>
                  Compare with fresh frame
                </button>
                {comparison && (
                  <div className="compare-images">
                    <figure>
                      <img
                        src={`data:image/jpeg;base64,${comparison.audit_frame}`}
                        alt="Saved calibration audit frame"
                      />
                      <figcaption>Saved calibration</figcaption>
                    </figure>
                    <figure>
                      <img
                        src={`data:image/jpeg;base64,${comparison.fresh_frame}`}
                        alt="Current camera frame"
                      />
                      <figcaption>
                        Current frame · difference{" "}
                        {comparison.difference_score?.toFixed(3) ??
                          "unavailable"}{" "}
                        {comparison.warning
                          ? "· check camera position"
                          : "· no large change"}
                      </figcaption>
                    </figure>
                  </div>
                )}
              </div>
            )}
          </section>
        )}

        {page === "Sessions" && (
          <section className="page-content">
            <div className="section-heading">
              <div>
                <div className="eyebrow">LOCAL HISTORY</div>
                <h2>Recorded sessions</h2>
                <p>Reports are built from each camera's local session files.</p>
              </div>
              <button type="button" onClick={() => void loadSessions()}>
                Refresh list
              </button>
            </div>
            {sessions.length === 0 ? (
              <div className="empty-state">
                <span>NO SESSIONS</span>
                <b>Nothing recorded yet</b>
                <p>
                  Completed recordings will appear here with their movement
                  summary.
                </p>
              </div>
            ) : (
              <div className="session-list">
                {sessions.map((session) => (
                  <article key={session.folder}>
                    <div className="session-head">
                      <b>{session.camera_id || "Camera"}</b>
                      <span>{session.status}</span>
                    </div>
                    <small>
                      Group {session.group_id} · {session.folder}
                    </small>
                    <p>
                      {session.summary ?? "No report summary is available."}
                    </p>
                  </article>
                ))}
              </div>
            )}
          </section>
        )}
      </main>
    </div>
  );
}
